import json
from pathlib import Path

from finance_agent.cli import main
from finance_agent.parsing import strip_code_fence

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "sample_data"
RECORDING = REPO_ROOT / "llm_recordings" / "run.json"


def test_replay_run_exits_zero_and_writes_a_valid_report(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # proves replay needs no key
    out = tmp_path / "report.json"

    code = main(["--data", str(DATA_DIR), "--out", str(out), "--replay", "--recording", str(RECORDING)])

    assert code == 0
    report = json.loads(out.read_text())
    assert set(report) == {"totals", "by_category", "flagged", "transactions", "summary"}
    assert set(report["totals"]) == {"income", "expenses", "net", "savings_rate"}


def test_missing_data_directory_exits_nonzero(tmp_path):
    code = main(["--data", str(tmp_path / "nope"), "--out", str(tmp_path / "report.json")])
    assert code != 0


def test_missing_api_key_without_replay_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = main(["--data", str(DATA_DIR), "--out", str(tmp_path / "report.json")])
    assert code != 0


def test_missing_recording_in_replay_mode_exits_nonzero(tmp_path):
    code = main(
        [
            "--data", str(DATA_DIR),
            "--out", str(tmp_path / "report.json"),
            "--replay",
            "--recording", str(tmp_path / "absent.json"),
        ]
    )
    assert code != 0


def _decision_responses_only(tmp_path):
    """A recording with the agent's planning answers but nothing else -- what a
    stale cache looks like after only the categorize/summary prompts changed."""
    recorded = json.loads(RECORDING.read_text())
    kept = {}
    for key, value in recorded.items():
        try:
            parsed = json.loads(strip_code_fence(value))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "tool" in parsed:
            kept[key] = value
    assert kept, "expected the recording to contain at least one decision response"
    path = tmp_path / "partial.json"
    path.write_text(json.dumps(kept))
    return path


def test_stale_recording_exits_nonzero_instead_of_writing_a_wrong_report(tmp_path, capsys):
    """A recording miss mid-run must not be swallowed as a tool error: doing so
    left every transaction uncategorized and mis-bucketed income as spend, with
    exit 0."""
    out = tmp_path / "report.json"

    code = main(
        [
            "--data", str(DATA_DIR),
            "--out", str(out),
            "--replay",
            "--recording", str(_decision_responses_only(tmp_path)),
        ]
    )

    assert code != 0
    assert not out.exists()
    assert "No recorded response for this prompt" in capsys.readouterr().err


def test_empty_recording_exits_nonzero_on_the_first_decision_call(tmp_path, capsys):
    path = tmp_path / "empty.json"
    path.write_text("{}")
    out = tmp_path / "report.json"

    code = main(["--data", str(DATA_DIR), "--out", str(out), "--replay", "--recording", str(path)])

    assert code != 0
    assert not out.exists()
    assert "error: No recorded response" in capsys.readouterr().err
