from finance_agent.models import Transaction
from finance_agent.report import build_flagged, compute_totals


def _txn(**kwargs) -> Transaction:
    defaults = dict(
        id="t",
        date="2024-01-01",
        description="d",
        raw_description="d",
        amount=0.0,
        category=None,
        source_file="test",
    )
    defaults.update(kwargs)
    return Transaction(**defaults)


def test_compute_totals_basic_income_and_expense():
    txns = [
        _txn(id="i1", amount=3000.0, category="Income"),
        _txn(id="e1", amount=-120.50, category="Food"),
        _txn(id="e2", amount=-45.0, category="Transportation"),
    ]
    totals, by_category = compute_totals(txns)
    assert totals["income"] == 3000.0
    assert totals["expenses"] == 165.5
    assert totals["net"] == 2834.5
    assert by_category == {"Income": 3000.0, "Food": 120.5, "Transportation": 45.0}


def test_compute_totals_savings_rate():
    txns = [
        _txn(id="i1", amount=1000.0, category="Income"),
        _txn(id="e1", amount=-250.0, category="Food"),
    ]
    totals, _ = compute_totals(txns)
    assert totals["savings_rate"] == 0.75


def test_compute_totals_zero_income_gives_zero_savings_rate():
    txns = [_txn(id="e1", amount=-100.0, category="Food")]
    totals, _ = compute_totals(txns)
    assert totals["savings_rate"] == 0.0


def test_compute_totals_refund_nets_against_category_not_income():
    txns = [
        _txn(id="i1", amount=3000.0, category="Income"),
        _txn(id="e1", amount=-130.0, category="Shopping"),
        _txn(id="r1", amount=35.0, category="Shopping"),
    ]
    totals, by_category = compute_totals(txns)
    assert totals["income"] == 3000.0  # refund must not inflate income
    assert totals["expenses"] == 95.0  # 130 - 35, netted within the category
    assert by_category["Shopping"] == 95.0


def test_compute_totals_excludes_flagged_transfer_and_pending():
    txns = [
        _txn(id="i1", amount=3000.0, category="Income"),
        _txn(id="t1", amount=-500.0, category="Transfer", exclude_from_totals=True),
        _txn(id="p1", amount=0.0, category="Uncategorized", exclude_from_totals=True),
        _txn(id="e1", amount=-50.0, category="Food"),
    ]
    totals, by_category = compute_totals(txns)
    assert totals["income"] == 3000.0
    assert totals["expenses"] == 50.0
    assert "Transfer" not in by_category
    assert totals["net"] == 2950.0


def test_compute_totals_never_touches_excluded_unconfirmed_income():
    txns = [
        _txn(id="i1", amount=3000.0, category="Income"),
        _txn(id="i2", amount=3000.0, category="Income", exclude_from_totals=True, flags=["unconfirmed"]),
    ]
    totals, _ = compute_totals(txns)
    assert totals["income"] == 3000.0


def test_build_flagged_collects_all_flag_reasons():
    txns = [
        _txn(id="a", description="A", flags=["reason 1"]),
        _txn(id="b", description="B", flags=["reason 2", "reason 3"]),
        _txn(id="c", description="C", flags=[]),
    ]
    flagged = build_flagged(txns)
    assert flagged == [
        {"description": "A", "date": "2024-01-01", "amount": 0.0, "reason": "reason 1"},
        {"description": "B", "date": "2024-01-01", "amount": 0.0, "reason": "reason 2"},
        {"description": "B", "date": "2024-01-01", "amount": 0.0, "reason": "reason 3"},
    ]


def test_build_flagged_disambiguates_repeated_descriptions_by_date_and_amount():
    txns = [
        _txn(id="a", date="2024-01-01", description="Salary", amount=3000.0, flags=[]),
        _txn(id="b", date="2024-01-15", description="Salary", amount=3000.0, flags=["unconfirmed"]),
    ]
    flagged = build_flagged(txns)
    assert flagged == [
        {"description": "Salary", "date": "2024-01-15", "amount": 3000.0, "reason": "unconfirmed"}
    ]
