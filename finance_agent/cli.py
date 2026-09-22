from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .agent import run_agent
from .config import DEFAULT_MODEL, DEFAULT_RECORDING_PATH, MAX_AGENT_STEPS
from .ingest import build_ledger
from .llm_client import AnthropicClient, RecordingClient, ReplayClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finance_agent", description="Personal finance agent")
    parser.add_argument("--data", required=True, type=Path, help="Directory containing the 4 sample CSVs")
    parser.add_argument("--out", required=True, type=Path, help="Path to write report.json")
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Replay LLM responses from the recording instead of calling the API",
    )
    parser.add_argument(
        "--recording",
        type=Path,
        default=DEFAULT_RECORDING_PATH,
        help=f"Path to the LLM recording file (default: {DEFAULT_RECORDING_PATH})",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--max-steps", type=int, default=MAX_AGENT_STEPS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.data.is_dir():
        print(f"error: data directory not found: {args.data}", file=sys.stderr)
        return 1

    try:
        transactions = build_ledger(args.data)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        print(f"error: failed to ingest data: {exc}", file=sys.stderr)
        return 1

    try:
        if args.replay:
            llm_client = ReplayClient(args.recording)
        else:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                print(
                    "error: ANTHROPIC_API_KEY is not set. Set it, or pass --replay to run "
                    "from the committed recording with no API access.",
                    file=sys.stderr,
                )
                return 1
            llm_client = RecordingClient(AnthropicClient(args.model, api_key=api_key), args.recording)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    result = run_agent(llm_client, transactions, args.out, max_steps=args.max_steps)

    print(f"Wrote {args.out} in {result['steps']} step(s)" + (" (forced finish)" if result["forced_finish"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
