from __future__ import annotations

import json

from .config import CATEGORIES, CATEGORY_BY_NORMALIZED
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


def _resolve_category(cat: object) -> tuple[str, str]:
    """Map one raw model answer to (canonical category, outcome).

    Outcome is "exact" when the model returned a category verbatim, "coerced"
    when it only differed by case or surrounding whitespace, and "rejected" when
    it was not a category at all (a hallucination, a non-string, or missing).
    Keeping coerced and rejected apart is what makes prompt drift visible: both
    used to collapse into a single "invalid" count.
    """
    if isinstance(cat, str):
        if cat in CATEGORIES:
            return cat, "exact"
        canonical = CATEGORY_BY_NORMALIZED.get(cat.strip().casefold())
        if canonical is not None:
            return canonical, "coerced"
    return "Uncategorized", "rejected"


def _parse_llm_categories(raw: str, pending: list[Transaction]) -> dict[str, tuple[str, str]]:
    try:
        data = json.loads(strip_code_fence(raw))
        if not isinstance(data, dict):
            raise ValueError("response was not a JSON object")
    except (json.JSONDecodeError, ValueError):
        data = {}

    return {txn.id: _resolve_category(data.get(txn.id)) for txn in pending}


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
    resolved = _parse_llm_categories(raw, pending)

    results: dict[str, str] = {}
    coerced = 0
    rejected = 0
    for txn in pending:
        assigned, outcome = resolved[txn.id]
        txn.category = assigned
        results[txn.id] = assigned
        if outcome == "coerced":
            coerced += 1
        elif outcome == "rejected":
            rejected += 1

    # Note: an explicit "Uncategorized" from the model is a valid answer and
    # counts as neither -- the old single counter inflated itself on those.
    return {
        "categorized": len(pending),
        "coerced": coerced,
        "rejected": rejected,
        "results": results,
    }
