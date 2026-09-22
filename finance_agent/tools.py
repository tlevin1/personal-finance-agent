from __future__ import annotations

import json

from .config import CATEGORIES
from .models import Transaction
from .parsing import strip_code_fence

TOOL_SPECS = [
    {
        "name": "categorize_transactions",
        "description": "Assign a category to the transactions that still have a blank category.",
        "args": {"transaction_ids": "list[str] (optional; defaults to all uncategorized)"},
    },
    {
        "name": "compute_totals",
        "description": (
            "Deterministically compute income, expenses, net, savings_rate, and "
            "per-category sums from the current transaction ledger. No arguments."
        ),
        "args": {},
    },
    {
        "name": "write_report",
        "description": "Serialize the final report.json to disk and end the run. Call only after totals are computed.",
        "args": {},
    },
]


def _build_categorize_prompt(pending: list[Transaction]) -> str:
    lines = [f'{t.id}: "{t.description}" amount={t.amount}' for t in pending]
    return (
        "You are categorizing personal-finance transactions.\n"
        f"Allowed categories (respond using exactly one of these strings per transaction): "
        f"{', '.join(CATEGORIES)}\n"
        "Respond with ONLY a JSON object mapping transaction id -> category string. No other text.\n"
        "Transactions:\n" + "\n".join(lines)
    )


def _parse_llm_categories(raw: str, pending: list[Transaction]) -> dict[str, str]:
    try:
        data = json.loads(strip_code_fence(raw))
        if not isinstance(data, dict):
            raise ValueError("response was not a JSON object")
    except (json.JSONDecodeError, ValueError):
        data = {}

    result = {}
    for txn in pending:
        cat = data.get(txn.id)
        result[txn.id] = cat if cat in CATEGORIES else "Uncategorized"
    return result


def categorize_transactions(
    llm_client, transactions_by_id: dict[str, Transaction], transaction_ids: list[str] | None
) -> dict:
    if transaction_ids is None:
        pending = [t for t in transactions_by_id.values() if not t.category]
    else:
        pending = [
            transactions_by_id[tid]
            for tid in transaction_ids
            if tid in transactions_by_id and not transactions_by_id[tid].category
        ]

    if not pending:
        return {"categorized": 0, "results": {}}

    prompt = _build_categorize_prompt(pending)
    raw = llm_client.complete(prompt)
    results = _parse_llm_categories(raw, pending)

    invalid_count = 0
    for txn in pending:
        assigned = results[txn.id]
        txn.category = assigned
        if assigned == "Uncategorized":
            invalid_count += 1

    return {"categorized": len(pending), "invalid_or_fallback": invalid_count, "results": results}
