"""Demo: make the model return garbage and watch the agent loop survive it.

Run from the repo root:  python demo_bad_response.py

A real model can't be made to emit malformed JSON on command, so this corrupts
one recorded response to a copy of the recording and runs the ordinary CLI
against it. Nothing is stubbed: the agent goes through the same ReplayClient
the normal --replay run uses, and sees exactly what it would have seen if the
live model had returned that text.
"""

import json
import tempfile
from pathlib import Path

from finance_agent.cli import main

GARBAGE = "Sure! I think the best next step is to categorize those transactions for you."

recording = json.loads(Path("llm_recordings/run.json").read_text())
target = next(key for key, value in recording.items() if '"tool"' in value)
recording[target] = GARBAGE

corrupted = Path(tempfile.mkdtemp()) / "corrupted_recording.json"
corrupted.write_text(json.dumps(recording, indent=2))

print(f"Corrupted 1 of {len(recording)} recorded responses:")
print(f"  {target[:12]}... -> {GARBAGE!r}\n")

out = Path(tempfile.mkdtemp()) / "report.json"
exit_code = main(["--data", "sample_data", "--out", str(out), "--replay", "--recording", str(corrupted)])

report = json.loads(out.read_text())
print(f"\nexit code: {exit_code}")
print(f"report keys: {sorted(report)}")
print(f"totals: {report['totals']}")
