# Take-Home Project: Personal Finance Agent

Thank you for your interest in the role. This take-home is a chance to show us
how you build a small AI system end to end: ingesting messy data, putting an
LLM to work where it adds value, keeping deterministic code in charge of the
numbers, and explaining your decisions.

There is no starter repository. Everything you need is in this document,
including the sample data. Start from a blank folder, in the language and
libraries of your choice.

## Timeline

- **Submit by the deadline in our email.** How much time you put in is up to
  you.
- If we move forward, you will present it in a **30-minute walkthrough**
  (section 9).

We grade the core scope only. Going bigger does not earn extra credit. A
finished core with honest notes beats an unfinished larger build every time.
If you run short on time, submit what works and say clearly what is missing.

---

## 1. The problem

Personal finance products turn raw bank and card exports into a clear monthly
picture: what came in, what went out, where the money went, and what deserves a
second look.

Build a small **tool-using AI agent** that:

1. Loads the four CSV files in section 5, including the deliberately messy one.
2. Uses an LLM to categorize transactions whose category is missing.
3. Computes all totals in **deterministic code**. The LLM is never trusted for
   arithmetic.
4. Runs a minimal **agentic loop**: the model picks a tool, sees the result,
   and decides what to do next. It must survive at least one bad model
   response without crashing.
5. Writes a structured `report.json` plus a short human-readable summary.

This is an agent, not a single prompt. The model decides which tool to call
(for example: categorize a batch, compute totals, write the report). Tools
return observations the agent acts on. Arithmetic lives in code, not in model
text.

---

## 2. Core requirements

Everything in this list is required. Nothing outside it is.

1. **Ingest all four CSVs.** `transactions_uncategorized.csv` has mixed date
   formats, blank categories, noisy merchant strings, a refund, a transfer, a
   zero-amount pending row, and a duplicate-looking charge. Handle these
   deliberately and write down your rules. There is no single right answer.
2. **Categorize with an LLM** behind a small interface you define. One method
   that takes a prompt and returns text is enough. Give the model a fixed list
   of categories and handle the case where it returns something else.
3. **Compute totals in code:** `income`, `expenses`, `net`, `savings_rate`, and
   per-category sums. Model output must never be copied into these numbers.
4. **Minimal agentic loop:** explicit tool dispatch, at least two tools the
   model can choose between, a step limit, and a failure path that still
   produces a report.
5. **Tests that run offline.** No network, no running model. Use a fake or
   scripted LLM client for anything that touches the model. Test the parser,
   the totals, and one failure path at minimum.
6. **Offline reproducibility.** During your real run, save every LLM response
   to a JSON file and commit it. Provide a flag or environment variable that
   replays from that file so we can run your agent end to end with no model.
7. **A CLI, no UI.** One documented command that takes a data directory and an
   output path. Exit `0` on success, non-zero on unrecoverable failure.

---

## 3. LLM setup

Use whatever you have access to. Our recommendation, in order:

- **Ollama, local and free:** `llama3.1:8b` or `qwen2.5:7b`. Small models
  return malformed JSON often, which is useful signal about your error handling.
- **OpenAI or Anthropic** API if you already have a key.

Use temperature 0. **Never commit API keys or a `.env` file.** Your submission
must run for us without any paid API, which is what the committed recording and
replay mode are for.

---

## 4. Output contract

Your CLI should look roughly like this (adjust to your language):

```bash
python -m finance_agent --data sample_data/ --out report.json
```

`report.json` must contain at least these keys. Additional keys are welcome.

```json
{
  "totals": {
    "income": 0.0,
    "expenses": 0.0,
    "net": 0.0,
    "savings_rate": 0.0
  },
  "by_category": {
    "Food": 0.0
  },
  "flagged": [
    { "description": "string", "reason": "string" }
  ],
  "transactions": [
    {
      "date": "YYYY-MM-DD",
      "description": "string",
      "amount": 0.0,
      "category": "string"
    }
  ],
  "summary": "Human-readable narrative of the month."
}
```

Rules:

- `totals.*` and `by_category` are computed by code, never by the LLM.
- `category` on each transaction may come from the LLM or from an existing
  label in the CSV.
- `flagged` may be empty. Anomaly detection is optional, but the key must exist.
- Normalize dates to `YYYY-MM-DD`.
- The `summary` may be LLM-written, but any numbers in it must come from your
  computed totals.

---

## 5. Sample data

Create a `sample_data/` folder and save each block below as the named file.
Files use the header shown in the first line. Some files intentionally overlap.

### `income.csv`

```csv
Date,Description,Amount,Source
2024-01-01,Salary,3000.00,Employer
2024-01-15,Freelance Work,500.00,Client A
2024-01-15,Salary,3000.00,Employer
2024-01-20,Consulting,750.00,Client B
2024-01-25,Dividend Payment,150.00,Investment
2024-01-30,Freelance Work,400.00,Client C
```

### `expenses.csv`

```csv
Date,Description,Amount,Category
2024-01-01,Grocery Store,-120.50,Food
2024-01-02,Gas Station,-45.00,Transportation
2024-01-03,Restaurant,-35.75,Food
2024-01-04,Amazon Purchase,-89.99,Shopping
2024-01-05,Netflix Subscription,-15.99,Entertainment
2024-01-06,Pharmacy,-25.30,Healthcare
2024-01-07,Uber Ride,-18.50,Transportation
2024-01-08,Coffee Shop,-4.50,Food
2024-01-09,Home Depot,-156.78,Home
2024-01-10,Restaurant,-42.00,Food
2024-01-11,Gym Membership,-50.00,Health
2024-01-12,Spotify Subscription,-9.99,Entertainment
2024-01-13,Grocery Store,-95.25,Food
2024-01-14,Car Insurance,-125.00,Insurance
2024-01-15,Restaurant,-28.50,Food
```

### `bank_statement.csv`

```csv
Date,Description,Amount,Balance,Type
2024-01-01,Salary Deposit,3000.00,5000.00,Credit
2024-01-02,Grocery Store,-120.50,4879.50,Debit
2024-01-03,Gas Station,-45.00,4834.50,Debit
2024-01-04,Restaurant,-35.75,4798.75,Debit
2024-01-05,Amazon Purchase,-89.99,4708.76,Debit
2024-01-06,Netflix Subscription,-15.99,4692.77,Debit
2024-01-07,Pharmacy,-25.30,4667.47,Debit
2024-01-08,Uber Ride,-18.50,4648.97,Debit
2024-01-09,Coffee Shop,-4.50,4644.47,Debit
2024-01-10,Home Depot,-156.78,4487.69,Debit
2024-01-11,Gym Membership,-50.00,4437.69,Debit
2024-01-12,Spotify Subscription,-9.99,4427.70,Debit
2024-01-13,Grocery Store,-95.25,4332.45,Debit
2024-01-14,Car Insurance,-125.00,4207.45,Debit
2024-01-15,Restaurant,-28.50,4178.95,Debit
2024-01-15,Freelance Payment,500.00,4678.95,Credit
2024-01-20,Consulting Fee,750.00,5428.95,Credit
2024-01-25,Dividend Payment,150.00,5578.95,Credit
```

### `transactions_uncategorized.csv`

This is the primary LLM categorization challenge.

```csv
Date,Description,Amount,Category
2024-01-02,WHOLEFDS MKT #10452,-87.34,
01/03/2024,SHELL OIL 5748291,-52.18,
2024-01-04,SQ *BLUE BOTTLE COFFEE,-6.75,Food
2024-01-05,AMZN MKTP US*AB12C3D4E,-129.99,
2024-1-6,Netflix.com,-15.99,Entertainment
2024-01-07,UBER   *TRIP HELP.UBER.COM,-23.40,
2024-01-08,CVS/PHARMACY #4412,-18.67,Healthcare
2024-01-09,TST* JOE'S PIZZA DOWNTOWN,-34.50,
01/10/2024,HOMEDEPOT.COM,-203.45,Home
2024-01-11,Spotify USA,-9.99,
2024-01-12,PAYPAL *ETSYSHOP,-45.00,Shopping
2024-01-13,CHECKCARD 1314 SAFEWAY #2910,-64.22,
2024-01-14,GEICO AUTO INSURANCE,-125.00,Insurance
2024-01-15,DOORDASH*CHIPOTLE,-18.99,
2024-01-16,VENMO *JOHN SMITH,-40.00,
2024-01-17,ATM WITHDRAWAL 001234,-100.00,
2024-01-18,APPLE.COM/BILL,-2.99,Entertainment
2024-01-19,WHOLEFDS MKT #10452,-87.34,
2024-01-20,TRANSFER TO SAVINGS,-500.00,
2024-01-21,POS DEBIT THE HOME DEPOT 123,-89.00,
2024-01-22,ZELLE PAYMENT TO LANDLORD,-1800.00,
2024-01-23,STARBUCKS STORE 11234,-5.45,Food
2024-01-24,UNKNOWN MERCHANT 998877,-12.00,
2024-01-25,Refund AMAZON.COM,34.99,
2024-01-26,ACH CREDIT PAYROLL ACME CORP,3200.00,
2024-01-27,COMCAST CABLE COMM,-89.99,Utilities
2024-01-28,LYFT *RIDE,-15.20,
2024-01-29,COSTCO WHSE #0421,-156.78,
2024-01-30,INTEREST CREDIT,1.25,
2024-01-31,PENDING AUTH TARGET T-8821,-0.00,
```

---

## 6. Optional extras

Only if the core is done, tested, and documented. Pick at most one.

- Duplicate-charge or anomaly detection populated into `flagged`.
- Categorization accuracy measured against the rows that already carry labels.

If you skip both, say so in one line. That is a perfectly good answer.

---

## 7. Using AI tools

We **encourage** you to use AI coding assistants (Claude, Cursor, Copilot,
ChatGPT, or anything else). We use them ourselves. What we care about is that
the code works and that you understand and can defend it.

Your README must include an **AI usage and decisions** section covering:

- Which tools you used and what they generated.
- What you changed, rejected, or rewrote, and why.
- Which design decisions are yours: the LLM-versus-code boundary, the tool
  design, the failure handling, the data-cleaning rules.

The walkthrough will focus on those decisions. A polished, AI-generated
codebase you cannot explain is a weaker submission than a smaller one you
fully own.

---

## 8. What to submit

By the deadline, send a link to a Git repository (public, or private with
access granted to us) or a zip archive containing:

- **Working code** we can run with the documented command.
- **Tests** that pass offline.
- **The committed LLM recording** and replay flag, plus the `report.json` from
  your run.
- **A `README.md`**, one to two pages, with:
  - How to set up and run, including which provider and model you used.
  - Roughly how long you spent.
  - Your data-cleaning rules and where you drew the LLM-versus-code line.
  - What you deliberately did not build, and what you would do with more time.
  - The **AI usage and decisions** section from section 7.
  - **Walkthrough notes:** three to five bullets on what you want to show us.

Do not include API keys, `.env` files, or any real personal financial data.

---

## 9. The 30-minute walkthrough

If we move forward, we will schedule a 30-minute call. Come with your code open
and ready to run. No slides. We will follow roughly this shape:

| Minutes | What we will ask |
| --- | --- |
| 0 to 2 | Run the agent in replay mode and give a two-minute overview. |
| 2 to 9 | Trace one messy transaction from CSV to `report.json`. |
| 9 to 15 | Show the exact line where totals are computed. Can model output reach it? |
| 15 to 21 | Make the model return garbage, live, and show what the loop does. |
| 21 to 26 | Your AI usage section: what did you change, and why? |
| 26 to 30 | With two more hours, what would you build and what would you skip? |

The time goes fast. Your **walkthrough notes** in the README are your prep.

---

## 10. How we evaluate

Roughly in priority order:

1. **LLM versus deterministic boundary.** Model does semantic work, code does
   the math, and model output is treated as untrusted.
2. **Messy input handling.** Mixed dates, blank labels, noisy merchants,
   refunds, transfers, and zero-amount rows are handled deliberately.
3. **Agent loop and tool design.** A real pick-tool, observe, decide loop with
   clear tool contracts and a step limit.
4. **Error recovery.** Bad model output degrades gracefully instead of killing
   the run.
5. **Testing and reproducibility.** Offline tests plus a replayable recording.
6. **Scoping judgment and documentation.** Core complete, clear notes on what
   was cut and why, and a README we can read in ten minutes.

Questions about the brief are welcome. Reply to this email and we will get back
to you quickly.

Good luck, and thank you for your time.
