from __future__ import annotations

from .models import Transaction


def compute_totals(transactions: list[Transaction]) -> tuple[dict, dict]:
    """Pure code. No LLM output ever reaches this function's arithmetic."""
    income_total = 0.0
    expense_total = 0.0  # signed: negative amounts (spend) minus positive refunds (netting down)
    by_category: dict[str, float] = {}

    for t in transactions:
        if t.exclude_from_totals:
            continue
        cat = t.category or "Uncategorized"
        by_category[cat] = round(by_category.get(cat, 0.0) + t.amount, 2)
        if cat == "Income":
            income_total += t.amount
        else:
            expense_total += t.amount

    for cat in by_category:
        if cat != "Income":
            by_category[cat] = round(abs(by_category[cat]), 2)

    net = income_total + expense_total
    savings_rate = round(net / income_total, 4) if income_total else 0.0

    totals = {
        "income": round(income_total, 2),
        "expenses": round(abs(expense_total), 2),
        "net": round(net, 2),
        "savings_rate": savings_rate,
    }
    return totals, by_category


def build_flagged(transactions: list[Transaction]) -> list[dict]:
    flagged = []
    for t in transactions:
        for reason in t.flags:
            # date/amount are extra (contract only requires description+reason),
            # but descriptions repeat across rows (e.g. "Salary" appears twice in
            # income.csv) so description alone can't identify which row this is.
            flagged.append(
                {"description": t.description, "date": t.date, "amount": t.amount, "reason": reason}
            )
    return flagged


def generate_summary(llm_client, totals: dict, by_category: dict) -> str:
    top_categories = sorted(
        (kv for kv in by_category.items() if kv[0] != "Income"),
        key=lambda kv: kv[1],
        reverse=True,
    )[:3]
    prompt = (
        "Write a 2-3 sentence human-readable summary of this month's personal finances.\n"
        "Use ONLY these exact numbers -- do not invent, recompute, or round differently:\n"
        f"Income: ${totals['income']:.2f}\n"
        f"Expenses: ${totals['expenses']:.2f}\n"
        f"Net: ${totals['net']:.2f}\n"
        f"Savings rate: {totals['savings_rate'] * 100:.1f}%\n"
        f"Top spending categories: {top_categories}\n"
        "Respond with ONLY the summary text, no preamble."
    )
    try:
        text = llm_client.complete(prompt).strip()
        if text:
            return text
    except Exception:
        pass
    return (
        f"Income was ${totals['income']:.2f} and expenses were ${totals['expenses']:.2f}, "
        f"for a net of ${totals['net']:.2f} ({totals['savings_rate'] * 100:.1f}% savings rate)."
    )


def build_report_dict(
    transactions: list[Transaction],
    totals: dict,
    by_category: dict,
    llm_client,
) -> dict:
    return {
        "totals": totals,
        "by_category": by_category,
        "flagged": build_flagged(transactions),
        "transactions": [t.to_report_dict() for t in transactions],
        "summary": generate_summary(llm_client, totals, by_category),
    }
