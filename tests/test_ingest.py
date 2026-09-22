from pathlib import Path

import pytest

from finance_agent.ingest import build_ledger, clean_merchant, normalize_date

DATA_DIR = Path(__file__).resolve().parent.parent / "sample_data"


def test_normalize_date_iso():
    assert normalize_date("2024-01-02") == "2024-01-02"


def test_normalize_date_non_padded():
    assert normalize_date("2024-1-6") == "2024-01-06"


def test_normalize_date_us_format():
    assert normalize_date("01/03/2024") == "2024-01-03"


def test_normalize_date_rejects_garbage():
    with pytest.raises(ValueError):
        normalize_date("not a date")


def test_clean_merchant_strips_known_processor_prefix():
    assert clean_merchant("SQ *BLUE BOTTLE COFFEE") == "BLUE BOTTLE COFFEE"
    assert clean_merchant("PAYPAL *ETSYSHOP") == "ETSYSHOP"
    assert clean_merchant("DOORDASH*CHIPOTLE") == "CHIPOTLE"


def test_clean_merchant_strips_trailing_store_number():
    assert clean_merchant("WHOLEFDS MKT #10452") == "WHOLEFDS MKT"
    assert clean_merchant("SHELL OIL 5748291") == "SHELL OIL"


def test_clean_merchant_leaves_ambiguous_strings_alone():
    # No rule for this shape -- left for the LLM to interpret, not silently mangled.
    assert clean_merchant("AMZN MKTP US*AB12C3D4E") == "AMZN MKTP US*AB12C3D4E"


def test_build_ledger_flags_unconfirmed_duplicate_salary():
    txns = build_ledger(DATA_DIR)
    salaries = [t for t in txns if t.source_file == "income.csv" and t.date == "2024-01-15" and t.amount == 3000.0]
    assert len(salaries) == 1
    salary = salaries[0]
    assert salary.exclude_from_totals is True
    assert any("bank_statement" in f for f in salary.flags)


def test_build_ledger_does_not_flag_income_outside_statement_coverage():
    txns = build_ledger(DATA_DIR)
    late_freelance = next(
        t for t in txns if t.source_file == "income.csv" and t.date == "2024-01-30"
    )
    assert late_freelance.exclude_from_totals is False
    assert late_freelance.flags == []


def test_build_ledger_confirms_expenses_despite_one_day_offset():
    txns = build_ledger(DATA_DIR)
    grocery = next(t for t in txns if t.source_file == "expenses.csv" and t.date == "2024-01-01")
    assert grocery.confirmed_by_bank is True
    assert grocery.exclude_from_totals is False


def test_build_ledger_flags_transfer_and_excludes_it():
    txns = build_ledger(DATA_DIR)
    transfer = next(t for t in txns if "TRANSFER TO SAVINGS" in t.raw_description)
    assert transfer.category == "Internal Transfer"
    assert transfer.exclude_from_totals is True


def test_build_ledger_flags_zero_amount_pending():
    txns = build_ledger(DATA_DIR)
    pending = next(t for t in txns if "PENDING AUTH" in t.raw_description)
    assert pending.exclude_from_totals is True


def test_build_ledger_flags_duplicate_looking_charge_without_excluding():
    txns = build_ledger(DATA_DIR)
    wholefds = [t for t in txns if "WHOLEFDS" in t.raw_description]
    assert len(wholefds) == 2
    assert all(t.exclude_from_totals is False for t in wholefds)
    assert all(any("duplicate" in f.lower() for f in t.flags) for t in wholefds)
