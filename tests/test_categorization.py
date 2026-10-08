import pytest

from finance_agent.config import CATEGORIES
from finance_agent.llm_client import ScriptedClient
from finance_agent.models import Transaction
from finance_agent.tools import _resolve_category, categorize_transactions


def _txn(txn_id: str) -> Transaction:
    return Transaction(
        id=txn_id,
        date="2024-01-02",
        description="WHOLEFDS MKT",
        raw_description="WHOLEFDS MKT #10452",
        amount=-87.34,
        category=None,
        source_file="transactions_uncategorized.csv",
    )


@pytest.mark.parametrize("answer", ["Food", "Income", "Uncategorized"])
def test_verbatim_category_is_exact(answer):
    assert _resolve_category(answer) == (answer, "exact")


@pytest.mark.parametrize("answer", ["food", "FOOD", " Food", "Food ", "  fOoD  "])
def test_case_and_whitespace_variants_are_coerced_to_canonical(answer):
    """A right answer formatted loosely must not be dumped in the same bucket
    as a hallucination -- and must not leak a variant spelling into the report,
    since compute_totals buckets on the exact string."""
    assert _resolve_category(answer) == ("Food", "coerced")


@pytest.mark.parametrize(
    "answer",
    [
        "Groceries",  # plausible but not in the allowed list
        "Internal Transfer",  # ingest-only, never offered to the model
        "",
        None,  # key missing from the response entirely
        123,
        ["Food"],
    ],
)
def test_non_categories_are_rejected(answer):
    assert _resolve_category(answer) == ("Uncategorized", "rejected")


def test_every_category_round_trips_through_its_own_lowercase_form():
    for category in CATEGORIES:
        canonical, outcome = _resolve_category(category.lower())
        assert canonical == category
        assert outcome in {"exact", "coerced"}


def test_categorize_counts_coerced_and_rejected_separately():
    by_id = {"a": _txn("a"), "b": _txn("b"), "c": _txn("c"), "d": _txn("d")}
    client = ScriptedClient(
        ['{"a": "Food", "b": "food", "c": "Groceries", "d": "Uncategorized"}']
    )

    result = categorize_transactions(client, by_id, None)

    assert result["categorized"] == 4
    assert result["coerced"] == 1  # only "food"
    assert result["rejected"] == 1  # only "Groceries"
    assert by_id["b"].category == "Food"  # canonical spelling, not the variant
    assert by_id["c"].category == "Uncategorized"
    assert by_id["d"].category == "Uncategorized"


def test_explicit_uncategorized_is_not_counted_as_a_failure():
    """Regression: the old single counter keyed off the assigned category, so a
    model correctly declining to classify inflated the invalid count."""
    by_id = {"a": _txn("a")}
    client = ScriptedClient(['{"a": "Uncategorized"}'])

    result = categorize_transactions(client, by_id, None)

    assert result["coerced"] == 0
    assert result["rejected"] == 0


def test_garbage_response_rejects_every_pending_transaction():
    by_id = {"a": _txn("a"), "b": _txn("b")}
    client = ScriptedClient(["not json at all"])

    result = categorize_transactions(client, by_id, None)

    assert result["rejected"] == 2
    assert all(t.category == "Uncategorized" for t in by_id.values())
