from __future__ import annotations

import csv
import re
from datetime import date, timedelta
from pathlib import Path

from rapidfuzz import fuzz

from .config import INTERNAL_TRANSFER_CATEGORY
from .models import Transaction

_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")

_KNOWN_PROCESSOR_PREFIXES = ("SQ", "TST", "PAYPAL", "DOORDASH", "VENMO")
_PROCESSOR_PATTERN = re.compile(
    r"^(?:" + "|".join(_KNOWN_PROCESSOR_PREFIXES) + r")\s*\*\s*", re.IGNORECASE
)
_POS_DEBIT_PATTERN = re.compile(r"^POS DEBIT\s+", re.IGNORECASE)
_CHECKCARD_PATTERN = re.compile(r"^CHECKCARD\s+\d+\s+", re.IGNORECASE)
_ACH_CREDIT_PATTERN = re.compile(r"^ACH CREDIT\s+", re.IGNORECASE)
_TRAILING_ID_PATTERN = re.compile(r"\s*#\d+$")
_TRAILING_NUMERIC_PATTERN = re.compile(r"\s+\d{3,}$")

_BANK_MATCH_WINDOW_DAYS = 1
_AMOUNT_EPSILON = 0.005
_DUPLICATE_SIMILARITY_THRESHOLD = 85  # rapidfuzz.fuzz.ratio, 0-100


def normalize_date(raw: str) -> str:
    """Normalize YYYY-MM-DD, YYYY-M-D, and MM/DD/YYYY to YYYY-MM-DD."""
    raw = raw.strip()
    m = _ISO_DATE.match(raw)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return date(y, mo, d).isoformat()
    m = _US_DATE.match(raw)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return date(y, mo, d).isoformat()
    raise ValueError(f"Unrecognized date format: {raw!r}")


def clean_merchant(raw: str) -> str:
    """Strip known payment-processor prefixes and trailing store/reference numbers.

    Not exhaustive by design: ambiguous strings (e.g. 'AMZN MKTP US*AB12C3D4E')
    are left as-is and handed to the LLM, which is better suited to that
    judgment call than a regex.
    """
    text = raw.strip()
    for pattern in (_POS_DEBIT_PATTERN, _CHECKCARD_PATTERN, _ACH_CREDIT_PATTERN, _PROCESSOR_PATTERN):
        text = pattern.sub("", text)
    text = _TRAILING_ID_PATTERN.sub("", text)
    text = _TRAILING_NUMERIC_PATTERN.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or raw.strip()


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def load_income(path: Path) -> list[Transaction]:
    rows = _read_csv(path)
    txns = []
    for i, row in enumerate(rows):
        txns.append(
            Transaction(
                id=f"income:{i}",
                date=normalize_date(row["Date"]),
                description=clean_merchant(row["Description"]),
                raw_description=row["Description"],
                amount=round(float(row["Amount"]), 2),
                category="Income",
                source_file="income.csv",
            )
        )
    return txns


def load_expenses(path: Path) -> list[Transaction]:
    rows = _read_csv(path)
    txns = []
    for i, row in enumerate(rows):
        txns.append(
            Transaction(
                id=f"expenses:{i}",
                date=normalize_date(row["Date"]),
                description=clean_merchant(row["Description"]),
                raw_description=row["Description"],
                amount=round(float(row["Amount"]), 2),
                category=row["Category"].strip() or None,
                source_file="expenses.csv",
            )
        )
    return txns


def load_bank_statement(path: Path) -> list[dict]:
    rows = _read_csv(path)
    parsed = []
    for row in rows:
        parsed.append(
            {
                "date": normalize_date(row["Date"]),
                "description": row["Description"],
                "amount": round(float(row["Amount"]), 2),
                "balance": round(float(row["Balance"]), 2),
            }
        )
    return parsed


def balance_column_reconciles(bank_rows: list[dict]) -> bool:
    """Check every row satisfies balance[i-1] + amount[i] == balance[i].

    bank_statement.csv is the only file carrying a running balance, which makes
    it self-auditing: if the arithmetic closes, the row set is complete and no
    entry is missing. That is what earns it the right to override
    income.csv/expenses.csv about whether money actually moved.
    """
    for prev, row in zip(bank_rows, bank_rows[1:]):
        if abs(prev["balance"] + row["amount"] - row["balance"]) > _AMOUNT_EPSILON:
            return False
    return True


def _match_bank_row(txn: Transaction, bank_rows: list[dict], used: set[int]) -> bool:
    txn_date = date.fromisoformat(txn.date)
    for idx, row in enumerate(bank_rows):
        if idx in used:
            continue
        if abs(row["amount"] - txn.amount) > _AMOUNT_EPSILON:
            continue
        row_date = date.fromisoformat(row["date"])
        if abs((row_date - txn_date).days) <= _BANK_MATCH_WINDOW_DAYS:
            used.add(idx)
            return True
    return False


def reconcile_with_bank(txns: list[Transaction], bank_rows: list[dict]) -> None:
    """Mark txns as confirmed/unconfirmed against bank_statement.csv (mutates in place).

    Only penalizes a missing match if the transaction date falls within the
    bank statement's own date coverage -- the statement only runs through
    2024-01-25, so a legitimate income entry dated after that shouldn't be
    flagged just because the statement doesn't extend that far.

    An unmatched transaction is only *excluded* from totals when the statement's
    balance column reconciles; otherwise the statement can't prove it is
    complete, so a missing match is reported but not acted on.
    """
    if not bank_rows:
        return
    trusted = balance_column_reconciles(bank_rows)
    bank_dates = [date.fromisoformat(r["date"]) for r in bank_rows]
    coverage_start, coverage_end = min(bank_dates), max(bank_dates)
    used: set[int] = set()
    for txn in txns:
        confirmed = _match_bank_row(txn, bank_rows, used)
        txn.confirmed_by_bank = confirmed
        if confirmed:
            continue
        txn_date = date.fromisoformat(txn.date)
        if not coverage_start <= txn_date <= coverage_end:
            continue
        coverage = f"{coverage_start.isoformat()}–{coverage_end.isoformat()}"
        if trusted:
            txn.exclude_from_totals = True
            txn.flags.append(
                f"No matching bank_statement entry within statement coverage "
                f"({coverage}); possible duplicate or data-entry error, "
                "excluded from totals."
            )
        else:
            txn.flags.append(
                f"No matching bank_statement entry within statement coverage "
                f"({coverage}), but the statement's balance column does not "
                "reconcile, so it cannot prove the entry is missing; kept in totals."
            )


def load_uncategorized(path: Path) -> list[Transaction]:
    rows = _read_csv(path)
    txns = []
    for i, row in enumerate(rows):
        raw_desc = row["Description"]
        desc_lower = raw_desc.lower()
        amount = round(float(row["Amount"]), 2)
        category = row["Category"].strip() or None

        txn = Transaction(
            id=f"uncategorized:{i}",
            date=normalize_date(row["Date"]),
            description=clean_merchant(raw_desc),
            raw_description=raw_desc,
            amount=amount,
            category=category,
            source_file="transactions_uncategorized.csv",
        )

        if "refund" in desc_lower:
            txn.flags.append("Refund: nets against its category's expense total rather than counting as income.")
        elif "transfer to" in desc_lower or "transfer from" in desc_lower:
            txn.category = INTERNAL_TRANSFER_CATEGORY
            txn.exclude_from_totals = True
            txn.flags.append("Internal transfer between own accounts; excluded from income/expense totals.")
        elif amount == 0:
            txn.exclude_from_totals = True
            txn.flags.append("Zero-amount pending authorization; unsettled, excluded from totals.")

        txns.append(txn)

    _flag_duplicates(txns)
    return txns


def _flag_duplicates(txns: list[Transaction]) -> None:
    """Same amount + a fuzzy-matched merchant name, rather than an exact string
    match, so two near-miss spellings of the same merchant (e.g. 'WHOLEFDS MKT'
    vs. 'WHOLE FOODS MKT') still get caught."""
    for i, txn in enumerate(txns):
        for other in txns[i + 1 :]:
            if abs(txn.amount - other.amount) > _AMOUNT_EPSILON:
                continue
            similarity = fuzz.ratio(txn.description, other.description)
            if similarity >= _DUPLICATE_SIMILARITY_THRESHOLD:
                txn.flags.append(
                    f"Possible duplicate of {other.id} (same amount, "
                    f"{similarity:.0f}% similar merchant name)."
                )
                other.flags.append(
                    f"Possible duplicate of {txn.id} (same amount, "
                    f"{similarity:.0f}% similar merchant name)."
                )


def build_ledger(data_dir: Path) -> list[Transaction]:
    income_txns = load_income(data_dir / "income.csv")
    expense_txns = load_expenses(data_dir / "expenses.csv")
    bank_rows = load_bank_statement(data_dir / "bank_statement.csv")
    reconcile_with_bank(income_txns + expense_txns, bank_rows)

    uncategorized_txns = load_uncategorized(data_dir / "transactions_uncategorized.csv")

    return income_txns + expense_txns + uncategorized_txns
