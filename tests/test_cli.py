import json
from pathlib import Path

from finance_agent.cli import main

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
