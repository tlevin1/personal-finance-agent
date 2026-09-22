# Personal Finance Agent

A small tool-using agent that ingests four CSVs (including one deliberately
messy one), uses an LLM to categorize transactions with a missing category,
computes all totals in deterministic code, and writes a structured
`report.json` plus a short narrative summary.

## Setup & running

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt        # + requirements-dev.txt for tests

# Real run (needs ANTHROPIC_API_KEY; also writes llm_recordings/run.json)
python -m finance_agent --data sample_data/ --out report.json

# Replay mode: no network call, no API key, reproduces the committed run
python -m finance_agent --data sample_data/ --out report.json --replay
```

Provider/model: **Anthropic, `claude-haiku-4-5-20251001`** (Haiku is more
than enough for a fixed-list classification task, and keeps the one real
recording run to a handful of cents).

Deviation from the brief: the installed SDK (`anthropic` 1.8.0, targeting the
Claude 5 model line) has dropped `temperature` from `messages.create`
entirely — it's not in the request schema, so it can't be set to 0. Noted in
[`finance_agent/llm_client.py`](finance_agent/llm_client.py).

Tests (offline, no network, no model):

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

**Time spent:** ~[fill in — architecture discussion + implementation + two
rounds of real-run debugging, done in one session].

## Data model

Four files, three roles:

- `income.csv` / `expenses.csv` — the categorized ledger. Every row already
  carries income vs. expense semantics.
- `bank_statement.csv` — **not** merged into the transaction list. It's the
  only file with a running balance, so it's used purely to *validate* the
  other two: I recompute `balance[i-1] + amount[i]` for every row and confirm
  it matches exactly, which establishes it as a trustworthy, self-audited
  ledger worth cross-checking against.
- `transactions_uncategorized.csv` — a separate, non-overlapping set of
  transactions (different dates/merchants/amounts from the other files) that
  is the actual LLM-categorization challenge.

`report.json`'s `transactions` array = `income.csv` + `expenses.csv` +
cleaned `transactions_uncategorized.csv`. `bank_statement.csv` rows are never
emitted directly.

## Data-cleaning rules (where I drew the LLM-vs-code line)

All of this is deterministic code — the LLM never sees or influences these
decisions, only the *category* of an already-cleaned row.

| Case | Rule | Why |
|---|---|---|
| Mixed date formats (`01/03/2024`, `2024-1-6`) | Regex-normalized to `YYYY-MM-DD`, handling both zero-padded and non-padded `YYYY-M-D` and `MM/DD/YYYY`. | Deterministic, unambiguous — no judgment needed. |
| Noisy merchant strings | Strip a curated set of known payment-processor prefixes (`SQ *`, `TST*`, `PAYPAL *`, `DOORDASH*`, `VENMO *`, `POS DEBIT `, `CHECKCARD ####`, `ACH CREDIT `) and trailing reference numbers (`#1234`, trailing 3+ digit codes). | Deliberately **not exhaustive** — e.g. `AMZN MKTP US*AB12C3D4E` is left alone. A regex normalizer chasing every processor format is scope creep; the ambiguous remainder is exactly what the LLM is better at, per the brief. |
| `expenses.csv` dated 1 day before the matching `bank_statement.csv` row, for all 15 rows | Not treated as a conflict — it's transaction date vs. posting date, a normal real-world pattern. `expenses.csv`'s date (the actual purchase date) is used. | Verified via the balance reconciliation described above, not assumed. |
| `income.csv`'s second "Salary $3000.00" on 2024-01-15, with **no** matching `bank_statement.csv` entry at all (not even off by a day) | Kept in the raw `transactions` list, added to `flagged`, **excluded from `totals.income`**. | `bank_statement.csv`'s balance column is internally self-consistent and only shows one salary credit all month — this entry looks like a duplicate/data-entry error. An unverified $3000 credit is too large to silently fold into the headline number. |
| `expenses.csv`'s "Restaurant -$42.00" on 2024-01-10, also with no `bank_statement.csv` counterpart | Same treatment: kept, flagged, excluded from `totals.expenses`. | Found the same way — the reconciliation code caught a genuine gap in the sample data I hadn't spotted by eye. |
| Entries dated after `bank_statement.csv`'s last date (2024-01-25) | **Not** flagged for lacking a bank match. | The statement only covers through 01-25; absence past that point isn't evidence of anything. Only gaps *within* its coverage window are suspicious. |
| Refund (`Refund AMAZON.COM, +34.99`) | Positive amount, but nets against its category's expense total rather than adding to `totals.income`. | It's money coming back for a prior purchase, not new earnings. |
| Internal transfer (`TRANSFER TO SAVINGS, -500.00`) | Category = `Internal Transfer` (assigned deterministically, never offered to the LLM as a choice), `exclude_from_totals = true`. | Money moving between the person's own accounts isn't spend. Kept out of the LLM's category list specifically so it can never be confused with the LLM's own (valid) use of "Transfer" for external transfers — see the bug notes below. |
| Zero-amount pending auth | Excluded from totals, flagged as unsettled. | It hasn't actually happened yet. |
| Duplicate-looking charge (`WHOLEFDS MKT #10452, -87.34` twice, 12 days apart) | **Kept in totals**, both flagged as a possible duplicate for human review. Detected via same amount + `rapidfuzz` similarity ≥ 85 on the cleaned description, not exact string match. | No bank statement covers this file to arbitrate, and two grocery trips at the same store, same total, 12 days apart is plausible. Dropping either is a coin flip with no evidence — surfacing beats guessing. Fuzzy matching also catches near-miss spellings of the same merchant (e.g. "WHOLEFDS MKT" vs "WHOLE FOODS MKT") that an exact-match check would miss — see `tests/test_ingest.py::test_flag_duplicates_catches_near_miss_spelling_via_fuzzy_match`. |
| `ZELLE`/`VENMO` payments to a person, ATM withdrawal | Sent to the LLM like any other transaction — not deterministically treated as transfers. | Unlike the savings transfer, this money actually leaves the person's control. |

Fixed category list given to the LLM: `Food, Transportation, Shopping,
Entertainment, Healthcare, Home, Health, Insurance, Utilities, Income,
Transfer, Uncategorized`. (`Health` and `Healthcare` are kept separate
because that's how `expenses.csv` already has them — not my call to merge
existing labels.)

## Agent & tool design

Three tools, dispatched by the model reading the current state each step
(not a hardcoded sequence):

- `categorize_transactions` — LLM assigns a category to whatever's still
  blank; anything the model returns outside the fixed list falls back to
  `"Uncategorized"`, never raises.
- `compute_totals` — pure code (`finance_agent/report.py:compute_totals`).
  Model output (a category string) can only ever change *which bucket* a
  transaction lands in — it never reaches the arithmetic.
- `write_report` — serializes `report.json`, ends the loop.

Failure handling: the model's tool-choice response is parsed as JSON; a
parse failure or unknown tool falls back to a deterministic
next-required-step instead of crashing. A hard step limit (`--max-steps`,
default 8) forces a finish — totals get computed with whatever's
categorized so far (blanks → `"Uncategorized"`) and the report is written
anyway. Exit code is 0 in both the clean and the forced-finish case; it's
only non-zero for real unrecoverable failures (missing data directory,
missing API key with no `--replay`, missing recording file). All three
paths are covered in `tests/test_agent_failure.py`.

## Offline reproducibility

`RecordingClient` wraps the real API client and writes every
`sha256(prompt) -> response` pair to `llm_recordings/run.json` as it runs.
`ReplayClient` reads the same file and never touches the network. I verified
this by running once for real, then running again with `ANTHROPIC_API_KEY`
unset and `--replay` passed, and diffing the two `report.json` outputs
programmatically — byte-identical.

## Two bugs only found by actually running it

Both caught by running the real agent against the live API and reading the
output, not by reasoning about the code in the abstract:

1. **Code-fenced JSON.** The model wrapped every response in
   ` ```json ... ``` `. My first parser used a strict `json.loads`, which
   rejected all of it — every categorization silently fell back to
   `"Uncategorized"`. Safe (nothing crashed), but wrong, and easy to miss if
   I'd only trusted the offline tests (which used clean, unfenced canned
   responses). Fixed with a small `strip_code_fence` helper
   (`finance_agent/parsing.py`) used before every `json.loads` call, plus a
   regression test.
2. **Category label collision.** The model reasonably chose `"Transfer"` for
   an ATM withdrawal — a real transaction, correctly counted in
   `totals.expenses`. But that string collided with the name I'd used for my
   *deterministic, excluded* internal-transfer rule, making the
   `by_category` breakdown misleading (same label, very different meaning).
   Fixed by reserving `"Internal Transfer"` for the deterministic rule only
   and keeping it out of the model's allowed category list.

## What I deliberately didn't build

- **Optional extras:** picked duplicate-charge flagging into `flagged`
  (already needed for the core "duplicate-looking charge" requirement, so it
  wasn't much extra). Skipped categorization-accuracy measurement against
  the rows that already carry labels.
- **Decimal arithmetic.** Totals use `float` + `round(..., 2)`, not
  `Decimal`. Fine at this scale; would switch for anything handling more
  transactions or currency conversion.
- **A merchant-name lookup table.** The regex cleaner handles known
  processor prefixes and trailing IDs but isn't exhaustive (e.g.
  `AMZN MKTP US*AB12C3D4E` stays as-is). A real system would want a
  merchant dictionary; out of scope here.
- **Batching in `categorize_transactions`.** One call handles all pending
  rows at once, since there are only ~20. Would batch for a larger ledger.
- **A CLI hook to inject garbage live.** The bad-response path is
  demonstrated in `tests/test_agent_failure.py` via `ScriptedClient`; there's
  no `--inject-garbage` flag for a live demo, though `ScriptedClient` makes
  one trivial to wire up if useful for the walkthrough.

## AI usage and decisions

Built with **Claude Code** (Anthropic) as a pair-programmer for the full
session: architecture discussion, code generation, and debugging.

**What Claude Code generated:** the module structure, all the
implementation code, the regex-based date/merchant cleaning, the test
suite, and this README's first drafts.

**What I directed and own:** the LLM-vs-code boundary (categorization only,
never arithmetic); the source-of-truth hierarchy for
`bank_statement.csv` vs. `income.csv`/`expenses.csv` (bank statement wins on
"did the money move," since it's the only self-auditable one; income/expense
wins on category, since bank statement has none); the specific call to
**exclude** the unconfirmed duplicate $3000 salary from `totals.income`
rather than include-and-flag it, after being shown the balance-reconciliation
evidence; the transfer/refund/pending-row treatment; and the three-tool
agent design (categorize / compute / write, with a step limit and a
deterministic fallback).

**What got changed after a real run exposed it, not before:** both bugs in
the section above. Neither was visible from reading the code — they only
showed up once the agent actually talked to a live model and I read the
resulting `report.json` line by line instead of trusting that "tests pass"
meant "output is right."

## Walkthrough notes

- Trace the duplicate $3000 salary: `income.csv` (row 3) →
  `ingest.reconcile_with_bank` (no matching bank_statement row, despite
  being within its coverage window) → `flagged` in `report.json`, excluded
  from `totals.income`. Same mechanism independently caught a second,
  unplanned anomaly (`expenses.csv`'s "Restaurant -$42.00").
- `finance_agent/report.py:compute_totals` — the one place arithmetic
  happens. Trace how `categorize_transactions` can only ever write a
  `category` string onto a `Transaction`, never a number, so there's no path
  from model output to the totals.
- Force a bad model response live via `ScriptedClient` and show
  `agent._parse_action` fall back to the deterministic next step instead of
  crashing, then still produce a valid `report.json`.
- The two "only found by running it" bugs — what they say about the gap
  between passing offline tests and a live model's actual behavior
  (markdown-fenced JSON, category-label collisions).
- With two more hours: Decimal arithmetic, a merchant lookup table instead
  of regex heuristics, and a `--inject-garbage` flag for a live failure demo.
