import json

from finance_agent.agent import run_agent
from finance_agent.llm_client import ScriptedClient
from finance_agent.models import Transaction


def _txns():
    return [
        Transaction(
            id="income:0",
            date="2024-01-01",
            description="Salary",
            raw_description="Salary",
            amount=3000.0,
            category="Income",
            source_file="income.csv",
        ),
        Transaction(
            id="uncategorized:0",
            date="2024-01-02",
            description="WHOLEFDS MKT",
            raw_description="WHOLEFDS MKT #10452",
            amount=-87.34,
            category=None,
            source_file="transactions_uncategorized.csv",
        ),
    ]


def test_agent_survives_malformed_json_and_still_produces_a_report(tmp_path):
    out_path = tmp_path / "report.json"
    responses = [
        "not json at all, sorry",  # step 1: decision call returns garbage
        '{"uncategorized:0": "Food"}',  # fallback categorize call succeeds
        '{"tool": "compute_totals", "args": {}}',
        '{"tool": "write_report", "args": {}}',
        "a two sentence summary of the month",
    ]
    client = ScriptedClient(responses)

    result = run_agent(client, _txns(), out_path, max_steps=8)

    assert result["success"] is True
    assert any(step["recovered_from_bad_response"] for step in result["trace"])
    assert out_path.exists()

    report = json.loads(out_path.read_text())
    assert report["totals"]["income"] == 3000.0
    assert set(report.keys()) == {"totals", "by_category", "flagged", "transactions", "summary"}


def test_agent_forces_finish_when_step_limit_hit_without_write_report(tmp_path):
    out_path = tmp_path / "report.json"
    # Model always returns a valid-looking action, but never picks write_report.
    responses = ['{"tool": "compute_totals", "args": {}}'] * 5 + ["a summary"]
    client = ScriptedClient(responses)

    result = run_agent(client, _txns(), out_path, max_steps=3)

    assert result["success"] is True
    assert result["forced_finish"] is True
    assert out_path.exists()
    report = json.loads(out_path.read_text())
    assert "totals" in report


def test_agent_falls_back_to_uncategorized_when_categorization_response_is_garbage(tmp_path):
    out_path = tmp_path / "report.json"
    responses = [
        '{"tool": "categorize_transactions", "args": {}}',
        "garbage, not a json object",  # categorize_transactions tool call itself gets garbage
        '{"tool": "compute_totals", "args": {}}',
        '{"tool": "write_report", "args": {}}',
        "summary text",
    ]
    client = ScriptedClient(responses)

    result = run_agent(client, _txns(), out_path, max_steps=8)

    assert result["success"] is True
    report = json.loads(out_path.read_text())
    txn = next(t for t in report["transactions"] if t["description"] == "WHOLEFDS MKT")
    assert txn["category"] == "Uncategorized"
