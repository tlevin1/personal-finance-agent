from __future__ import annotations

import json
from pathlib import Path

from .config import MAX_AGENT_STEPS
from .models import Transaction
from .parsing import strip_code_fence
from .report import build_report_dict, compute_totals
from .tools import TOOL_SPECS, categorize_transactions


def _build_decision_prompt(pending_count: int, state: dict) -> str:
    return (
        "You are a finance agent choosing the next tool to call.\n"
        f"Available tools: {json.dumps(TOOL_SPECS)}\n"
        f"Current state: {pending_count} transactions still uncategorized; "
        f"totals_computed={state['totals_computed']}; report_written={state['report_written']}.\n"
        'Respond with ONLY a JSON object: {"tool": "<name>", "args": {}}. No other text.'
    )


def _parse_action(raw: str) -> dict | None:
    try:
        data = json.loads(strip_code_fence(raw))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "tool" not in data:
        return None
    return data


def _deterministic_fallback(pending_count: int, state: dict) -> dict:
    if pending_count:
        return {"tool": "categorize_transactions", "args": {}}
    if not state["totals_computed"]:
        return {"tool": "compute_totals", "args": {}}
    return {"tool": "write_report", "args": {}}


def run_agent(
    llm_client,
    transactions: list[Transaction],
    out_path: Path,
    max_steps: int = MAX_AGENT_STEPS,
) -> dict:
    transactions_by_id = {t.id: t for t in transactions}
    state = {"totals_computed": False, "report_written": False}
    totals: dict | None = None
    by_category: dict | None = None
    trace: list[dict] = []

    for step in range(1, max_steps + 1):
        pending_count = sum(1 for t in transactions if not t.category)
        prompt = _build_decision_prompt(pending_count, state)
        raw = llm_client.complete(prompt)
        action = _parse_action(raw)

        recovered_from_bad_response = action is None
        if action is None:
            action = _deterministic_fallback(pending_count, state)

        tool = action.get("tool")
        args = action.get("args") or {}

        try:
            if tool == "categorize_transactions":
                observation = categorize_transactions(
                    llm_client, transactions_by_id, args.get("transaction_ids")
                )
            elif tool == "compute_totals":
                totals, by_category = compute_totals(transactions)
                state["totals_computed"] = True
                observation = {"totals": totals, "by_category": by_category}
            elif tool == "write_report":
                if not state["totals_computed"]:
                    totals, by_category = compute_totals(transactions)
                    state["totals_computed"] = True
                report = build_report_dict(transactions, totals, by_category, llm_client)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(report, indent=2))
                state["report_written"] = True
                observation = {"written": str(out_path)}
            else:
                observation = {"error": f"unknown tool {tool!r}"}
        except Exception as exc:  # a tool failing must not crash the agent loop
            observation = {"error": str(exc)}

        trace.append(
            {
                "step": step,
                "tool": tool,
                "recovered_from_bad_response": recovered_from_bad_response,
                "observation": observation,
            }
        )

        if state["report_written"]:
            return {"success": True, "steps": step, "forced_finish": False, "trace": trace}

    # Step limit reached without the model finishing the job on its own --
    # this is the required failure path: still produce a report.
    if not state["totals_computed"]:
        totals, by_category = compute_totals(transactions)
    report = build_report_dict(transactions, totals, by_category, llm_client)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    trace.append({"step": max_steps + 1, "tool": "write_report", "observation": {"forced": True}})
    return {"success": True, "steps": max_steps, "forced_finish": True, "trace": trace}
