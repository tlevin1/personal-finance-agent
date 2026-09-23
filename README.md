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

# Replay mode: no network call, no API key needed, reproduces the committed run
python -m finance_agent --data sample_data/ --out report.json --replay

# Real run (needs ANTHROPIC_API_KEY; also refreshes llm_recordings/run.json)
python -m finance_agent --data sample_data/ --out report.json
```

Exit code is `0` on success (including the forced-finish path below) and
non-zero for unrecoverable failures: missing data directory, missing API key
without `--replay`, or a missing recording file.

Runs on **Python 3.9–3.14** (verified on 3.9, 3.11 and 3.14). The replay path
touches no network and needs no API key — and the `anthropic` SDK is imported
lazily inside `AnthropicClient`, so `--replay` reproduces the committed
`report.json` byte-for-byte even with `anthropic` not installed at all. Only
`rapidfuzz` is required for it.

Provider/model: **Anthropic, `claude-haiku-4-5-20251001`** (Haiku is more than
enough for fixed-list classification, and keeps the one real recording run to a
handful of cents).

Tests — offline, no network, no model:

```bash
pip install -r requirements-dev.txt
pytest tests/ -v        # 37 tests
```

**Deviation from the brief:** the installed SDK (`anthropic` 1.8.0, targeting
the Claude 5 model line) has dropped `temperature` from `messages.create`
entirely — it is not in the request schema, so it cannot be set to 0. Noted in
[`finance_agent/llm_client.py`](finance_agent/llm_client.py).

**Time spent:** ~2 hours. Roughly 30 minutes on the data model and the
LLM-vs-code boundary (the source-of-truth call between `bank_statement.csv` and
`income.csv`/`expenses.csv`, the transfer/refund/duplicate rules) before writing
any code, ~35 minutes implementing with Claude Code and running it for real, and
the balance on a review pass: implementing the balance reconciliation this README
had described but never actually done, adding CLI exit-code coverage, and chasing
down the third bug below.

## Data model

Four files, three roles:

- `income.csv` / `expenses.csv` — the categorized ledger. Every row already
  carries income-vs-expense semantics.
- `bank_statement.csv` — **not** merged into the transaction list. It is the
  only file with a running balance, so it is used purely to *validate* the
  other two (see below).
- `transactions_uncategorized.csv` — a separate, non-overlapping set of
  transactions (different dates, merchants and amounts from the other files).
  This is the actual LLM-categorization challenge.

`report.json`'s `transactions` array = `income.csv` + `expenses.csv` + cleaned
`transactions_uncategorized.csv`. `bank_statement.csv` rows are never emitted
directly.

### Why the bank statement is allowed to overrule the other two

`balance_column_reconciles` ([`finance_agent/ingest.py`](finance_agent/ingest.py))
checks that every row satisfies `balance[i-1] + amount[i] == balance[i]`. The
sample statement passes exactly. That closure is the evidence that the row set
is *complete* — no entry is missing — which is what earns it the right to say a
transaction in `income.csv`/`expenses.csv` never actually happened.

The check is load-bearing, not decorative: if the balance column does not
reconcile, `reconcile_with_bank` downgrades every unmatched transaction from
"excluded from totals" to "flagged only", because a statement that cannot prove
it is complete cannot prove anything is missing from it. Covered by
`test_unmatched_txn_is_flagged_but_kept_when_balance_does_not_reconcile`.

Matching is on amount (±0.005) within a **±1 day window**, because the two files
do not agree on dates uniformly: the first nine `expenses.csv` rows appear in the
statement one day later (transaction date vs. posting date), while the last five
appear same-day. A window absorbs both without needing to model which convention
applies where.

## Data-cleaning rules (where I drew the LLM-vs-code line)

All of this is deterministic code. The LLM never sees or influences these
decisions — only the *category* of an already-cleaned row.

| Case | Rule | Why |
|---|---|---|
| Mixed date formats (`01/03/2024`, `2024-1-6`) | Regex-normalized to `YYYY-MM-DD`, handling zero-padded and non-padded `YYYY-M-D` plus `MM/DD/YYYY`. Anything else raises. | Deterministic and unambiguous — no judgment needed. |
| Noisy merchant strings | Strip a curated set of payment-processor prefixes (`SQ *`, `TST*`, `PAYPAL *`, `DOORDASH*`, `VENMO *`, `POS DEBIT `, `CHECKCARD ####`, `ACH CREDIT `) and trailing reference numbers (`#1234`, trailing 3+ digit codes). | Deliberately **not exhaustive** — e.g. `AMZN MKTP US*AB12C3D4E` is left alone. A regex chasing every processor format is scope creep; the ambiguous remainder is exactly what the LLM is better at. |
| `income.csv` line 4: a second `Salary` for $3,000.00 on 2024-01-15, with **no** `bank_statement.csv` counterpart anywhere | Kept in the raw `transactions` list, added to `flagged`, **excluded from `totals.income`**. | The statement's balance column reconciles and shows only one salary credit all month. An unverified $3,000 credit is too large to fold silently into the headline number. |
| `expenses.csv` line 11: `Restaurant -$42.00` on 2024-01-10, also with no counterpart | Same treatment: kept, flagged, excluded from `totals.expenses`. | Found by the same generic reconciliation pass, not a special case — see the walkthrough notes. |
| Entries dated after the statement's last date (2024-01-25) | **Not** flagged for lacking a bank match. | The statement only covers through 01-25; absence past that point is not evidence of anything. Only gaps *inside* the coverage window are suspicious. |
| Refund (`Refund AMAZON.COM`, +34.99) | Positive amount, but nets against its category's expense total rather than adding to `totals.income`. | Money coming back for a prior purchase is not new earnings. |
| Internal transfer (`TRANSFER TO SAVINGS`, -500.00) | Category = `Internal Transfer` (assigned deterministically, never offered to the LLM), `exclude_from_totals = true`. | Money moving between the person's own accounts is not spend. Kept out of the LLM's category list specifically so it can never collide with the model's own valid use of `Transfer` — see bug 2 below. |
| Zero-amount pending auth | Excluded from totals, flagged as unsettled. | It has not actually happened yet. |
| Duplicate-looking charge (`WHOLEFDS MKT #10452`, -87.34, twice, 12 days apart) | **Kept in totals**, both rows flagged for human review. Detected by same amount + `rapidfuzz` similarity ≥ 85 on the cleaned description, not exact string match. | No bank statement covers this file to arbitrate, and two grocery trips at the same store for the same total 12 days apart is plausible. Dropping either is a coin flip with no evidence — surfacing beats guessing. Fuzzy matching also catches near-miss spellings of one merchant (`WHOLEFDS MKT` vs. `WHOLE FOODS MKT`) that exact matching would miss. |
| `ZELLE`/`VENMO` payments to a person, ATM withdrawal | Sent to the LLM like any other transaction — **not** deterministically treated as transfers. | Unlike the savings transfer, this money actually leaves the person's control. |

Fixed category list given to the LLM: `Food, Transportation, Shopping,
Entertainment, Healthcare, Home, Housing, Health, Insurance, Utilities, Income,
Transfer, Uncategorized`. (`Health` and `Healthcare` are kept separate because
that is how `expenses.csv` already labels them — not my call to merge existing
labels. `Home` vs. `Housing` is my own split, and bug 3 below is why.)

## Agent & tool design

Three tools, dispatched by the model reading the current state each step — not a
hardcoded sequence:

- `categorize_transactions` — the LLM assigns a category to whatever is still
  blank. Anything it returns outside the fixed list falls back to
  `"Uncategorized"`; it never raises.
- `compute_totals` — pure code
  ([`finance_agent/report.py`](finance_agent/report.py), `compute_totals`).
- `write_report` — serializes `report.json` and ends the loop.

**The LLM-vs-code boundary.** Model output reaches exactly one field:
`Transaction.category`, a string. Inside `compute_totals` that string is only
ever used as a dict key to pick a bucket; every number summed is `t.amount`,
parsed from the CSV. There is no code path from model text to an arithmetic
operand. The narrative `summary` is LLM-written, but the prompt injects the
already-computed figures and instructs the model not to recompute them, and
there is a deterministic fallback string if the call fails or returns empty.

**Failure handling.** The model's tool-choice response is parsed as JSON; a
parse failure or an unknown tool falls back to a deterministic next-required-step
instead of crashing. Any exception raised inside a tool is caught and returned to
the loop as an observation. A hard step limit (`--max-steps`, default 8) forces a
finish: totals are computed from whatever is categorized so far (blanks →
`"Uncategorized"`) and the report is written anyway.

## Offline reproducibility

`RecordingClient` wraps the real API client and writes every
`sha256(prompt) -> response` pair to `llm_recordings/run.json` as it runs.
`ReplayClient` reads that file and never touches the network. Verified by running
once for real, then again with `ANTHROPIC_API_KEY` unset and `--replay` passed,
and diffing the two `report.json` outputs — byte-identical.

## Tests

37 tests, all offline, no network and no model:

| File | Covers |
|---|---|
| `test_ingest.py` (19) | Date normalization, merchant cleaning, balance reconciliation and its downgrade path, transfer/pending/duplicate rules, coverage-window logic. |
| `test_totals.py` (8) | Income/expense/net/savings-rate arithmetic, refund netting, exclusion of flagged rows, `flagged` construction. |
| `test_agent_failure.py` (3) | Malformed tool-choice JSON, garbage inside `categorize_transactions`, step-limit forced finish — each still producing a valid report. |
| `test_cli.py` (4) | Exit `0` on a replay run with no API key present; non-zero for missing data dir, missing key without `--replay`, and missing recording. |
| `test_parsing.py` (3) | Code-fence stripping (regression test for bug 1). |

### Demonstrating recovery from a bad model response

A real model cannot be made to emit malformed JSON on command, so
`python demo_bad_response.py` corrupts one recorded response in a copy of the
recording and runs the **ordinary CLI** against it. Nothing is stubbed — the
agent goes through the same `ReplayClient` a normal `--replay` run uses, and
sees exactly what it would have seen had the live model returned that text.

The CLI prints its step trace, so the recovery is visible rather than implied:

```
step 1: categorize_transactions
step 2: compute_totals
step 3: write_report  <- model response unparseable; fell back to next required step
Wrote /tmp/.../report.json in 3 step(s)
```

Totals and exit code are identical to the clean run; only the trace differs.

## Three bugs only found by actually running it

All caught by running the real agent against the live API and reading the
output, not by reasoning about the code in the abstract:

1. **Code-fenced JSON.** The model wrapped every response in ` ```json ... ``` `.
   My first parser used a strict `json.loads`, which rejected all of it — every
   categorization silently fell back to `"Uncategorized"`. Safe (nothing crashed)
   but wrong, and easy to miss if I had only trusted the offline tests, which
   used clean, unfenced canned responses. Fixed with a `strip_code_fence` helper
   ([`finance_agent/parsing.py`](finance_agent/parsing.py)) applied before every
   `json.loads`, plus a regression test.
2. **Category label collision.** The model reasonably chose `"Transfer"` for an
   ATM withdrawal — a real transaction, correctly counted in `totals.expenses`.
   But that string collided with the name I had used for my *deterministic,
   excluded* internal-transfer rule, making `by_category` misleading: same label,
   very different meaning. Fixed by reserving `"Internal Transfer"` for the
   deterministic rule and keeping it out of the model's allowed category list.
3. **Rent hiding inside `Transfer`.** Reading the finished `report.json`, the
   narrative summary announced that the month's top spending category was
   *Transfers, $1,840* — which turned out to be `ZELLE PAYMENT TO LANDLORD`
   (-$1,800) plus a $40 Venmo. The month's largest real expense, rent, was
   buried in a generic bucket and headlining the summary. My category list had
   no home for it: the list was derived from labels already present in
   `expenses.csv`, and none of them covers rent, so the model picked the nearest
   thing to a description whose only real signal is the payment rail. Fixed by
   adding a distinct `Housing` category and re-recording.

   Worth noting what that re-run demonstrated: exactly one transaction changed
   category, `Transfer` fell from $1,840 to $40, `Housing` appeared at $1,800 —
   and `income`, `expenses`, `net` and `savings_rate` did not move by a cent.
   Recategorization can only ever move money between buckets, because the
   arithmetic never reads model output.

## What I deliberately didn't build

- **Optional extras:** took the duplicate-charge/anomaly-detection extra
  (`flagged`), since the core already required handling the duplicate-looking
  charge. Skipped measuring categorization accuracy against the pre-labelled rows.
- **Decimal arithmetic.** Totals use `float` + `round(..., 2)`, not `Decimal`.
  Fine at this scale; I would switch for a larger ledger or currency conversion.
- **A merchant-name lookup table.** The regex cleaner handles known processor
  prefixes and trailing IDs but is not exhaustive. A real system wants a merchant
  dictionary; out of scope here.
- **Batching in `categorize_transactions`.** One call handles all pending rows,
  since there are only ~20. Would batch for a larger ledger.
- **Cross-file duplicate detection.** `_flag_duplicates` only runs within
  `transactions_uncategorized.csv`; the reconciliation pass covers the other two.
- **A loop where the model's choices genuinely branch.** Worth being explicit:
  for this task the tool order really is fixed — you must categorize before
  totalling and total before writing — so `_deterministic_fallback` encodes the
  same order the model picks, and the run would produce an identical report if
  the model's choice were ignored entirely. That is deliberate rather than
  accidental: it is exactly what makes the failure path safe, and inventing
  branching the task does not have would be fabricated complexity. A problem with
  real ambiguity (which account to reconcile first, whether to re-categorize
  low-confidence rows) would justify a richer loop.

## AI usage and decisions

Built with **Claude Code** (Anthropic) as a pair-programmer for the full session:
architecture discussion, code generation, and debugging.

**What Claude Code generated:** the module structure, the implementation code,
the regex date/merchant cleaning, the test suite, and this README's first drafts.

**What I directed and own:** the LLM-vs-code boundary (categorization only, never
arithmetic); the source-of-truth hierarchy between `bank_statement.csv` and
`income.csv`/`expenses.csv` (the statement wins on "did the money move", because
it is the only self-auditable file; income/expenses win on category, because the
statement has none); the decision to **exclude** the unconfirmed $3,000 salary
from `totals.income` rather than include-and-flag it, after seeing the
balance-reconciliation evidence; the transfer/refund/pending-row treatment; and
the three-tool agent design with a step limit and deterministic fallback.

**What changed only because a real run exposed it:** all three bugs above. None
was visible from reading the code — they surfaced once the agent talked to a live
model and I read the resulting `report.json` line by line, instead of assuming
"tests pass" meant "output is right". The third one was not a crash or a parse
error at all; the pipeline was working exactly as written and still produced a
bad answer, which is the failure mode offline tests are worst at catching.

**What I rewrote after review:** the balance reconciliation was originally
described in this README but never actually implemented — the code read the
`Balance` column and discarded it. Since the $3,000 exclusion rests entirely on
that argument, I implemented the check for real and made it gate the exclusion
behavior, rather than softening the claim.

## Walkthrough notes

- **Trace the duplicate salary:** `income.csv` line 4 (the second `Salary`,
  2024-01-15, $3,000.00 — note line 3 is `Freelance Work`) → `reconcile_with_bank`
  finds no bank row with that amount within ±1 day, inside the statement's
  coverage window → `flagged` in `report.json`, excluded from `totals.income`.
- **The second anomaly I did not plan for:** the same generic pass also flagged
  `expenses.csv` line 11, `Restaurant -$42.00` on 2024-01-10. Every other expense
  row has a same-amount bank row within a day; this one has no match at
  *any* date — `-42.00` does not appear in `bank_statement.csv` at all. I wrote no
  special case for it, which is the point: the reconciliation generalizes rather
  than being fitted to the one anomaly the brief calls out.
- **The arithmetic boundary:** `compute_totals` in
  [`finance_agent/report.py`](finance_agent/report.py) — the only place numbers
  are produced. Model output enters as `t.category`, used solely as a dict key;
  every summed value is `t.amount` from the CSV. Bug 3 is the live proof: adding
  a `Housing` category and re-running moved $1,800 between buckets and left
  `income`, `expenses`, `net` and `savings_rate` byte-identical.
- **Force a bad model response:** `python demo_bad_response.py` corrupts one
  recorded response and runs the real CLI against it — no stubs, same
  `ReplayClient` as a normal run. The step trace shows `_parse_action` failing
  and `_deterministic_fallback` taking over; totals and exit code come out
  identical to the clean run.
- **With two more hours:** `Decimal` arithmetic, a merchant lookup table instead
  of regex heuristics, and categorization-accuracy measurement against the
  pre-labelled rows.
