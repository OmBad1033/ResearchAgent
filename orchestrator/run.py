"""Dynamic A2A orchestrator: plan -> delegate -> loop until done.

Usage:
    python3.11 -m orchestrator.run --domain "fintech"
    python3.11 -m orchestrator.run --domain "fintech" --agents orchestrator/agents.yaml
    python3.11 -m orchestrator.run --domain "fintech" --research-url http://127.0.0.1:8001
    python3.11 -m orchestrator.run --domain "fintech" --auto    # no human input() pauses
    ORCHESTRATOR_MODEL=meta/muse-spark-1.3-contributor python3.11 -m orchestrator.run --domain fintech

Flow:
    1. Load agents.yaml (MCP-style: key -> {url, enabled}), fetch each
       enabled agent's Agent Card (fail fast if one is down).
    2. Planner (muse-spark-1.3-contributor via OpenRouter) sees the goal +
       skill descriptions and picks ONE next delegation, or finishes.
    3. Executor sends the A2A message (reusing contextId per agent),
       drives the task to COMPLETED / INPUT_REQUIRED / failure, and
       appends the artifact to the trace.
    4. Repeat until the planner says finish or --max-steps is hit.
    5. Print the summary + write runs/<timestamp>/result.json.

INPUT_REQUIRED (an agent asking a question mid-run, e.g. approval):
    interactive mode asks via input(); --auto treats it as a failure.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrator.a2a_client import (
    STATE_AUTH_REQUIRED,
    STATE_COMPLETED,
    STATE_INPUT_REQUIRED,
    FAILED_STATES,
)
from orchestrator.executor import (
    delegate,
    summarize_artifact,
)
from orchestrator.planner import (
    decide_next_step,
    resolve_planner_model,
)
from orchestrator.registry import (
    AgentRecord,
    discover_agents,
    format_agents_for_prompt,
)

CALL_TIMEOUT_S = 300.0
MAX_STEPS = 10


async def _run(
    domain: str,
    agents_config: str | None,
    overrides: dict[str, str],
    max_steps: int,
    auto: bool,
    planner_model: str | None,
    poll_interval_s: float = 3.0,
) -> int:
    try:
        agents = await discover_agents(config_path=agents_config, overrides=overrides)
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        print(f"[orchestrator] {exc}")
        return 2
    by_key = {rec.key: rec for rec in agents}
    for rec in agents:
        skill_ids = ", ".join(
            str(s.get("id") or s.get("name")) for s in rec.skills
        ) or "(no skills listed)"
        print(f"[orchestrator] {rec.key}: {rec.name} v{rec.version} — {skill_ids}")

    agents_block = format_agents_for_prompt(agents)
    model = resolve_planner_model(planner_model)
    print(f"[orchestrator] Planner model: {model}")
    print(f"[orchestrator] Goal: {domain!r} (max {max_steps} steps)")

    trace: list[dict[str, Any]] = []
    context_ids: dict[str, str] = {}
    # Full artifacts by agent key, so the planner can reference items by id
    # (e.g. {"opportunity_id": ...}) without echoing kilobytes of JSON back
    # through the LLM. The runner resolves the reference into the DataPart.
    artifacts: dict[str, Any] = {}
    step = 0
    while step < max_steps:
        step += 1
        try:
            decision = await asyncio.to_thread(
                decide_next_step,
                domain,
                agents_block,
                trace,
                [rec.key for rec in agents],
                planner_model,
            )
        except Exception as exc:
            print(f"[orchestrator] Planner failed: {exc}")
            return 1

        if decision.action == "finish":
            print(f"[orchestrator] Done after {step - 1} delegation(s).")
            if decision.summary:
                print(f"\n===== RESULT =====\n{decision.summary}")
            _save_run(domain, trace, decision.summary, agents)
            return 0

        rec = by_key[decision.agent or ""]
        print(f"[orchestrator] Step {step}: -> {rec.key} ({decision.reasoning})")
        try:
            data_input = _resolve_data_input(decision.data_input, artifacts, domain)
        except ValueError as exc:
            print(f"[orchestrator] Cannot resolve delegation input: {exc}")
            trace.append(
                {"agent": rec.key, "state": "UNRESOLVABLE_INPUT", "error": str(exc)}
            )
            continue
        try:
            result = await delegate(
                rec.key,
                rec.url,
                text_input=decision.text_input,
                data_input=data_input,
                context_id=context_ids.get(rec.key),
                timeout_s=CALL_TIMEOUT_S,
                poll_interval_s=poll_interval_s,
            )
        except Exception as exc:
            print(f"[orchestrator] Delegation to {rec.key} failed: {exc}")
            trace.append(
                {"agent": rec.key, "state": "TRANSPORT_ERROR", "error": str(exc)}
            )
            continue

        if result.context_id:
            context_ids[rec.key] = result.context_id
        if result.artifact is not None:
            artifacts[rec.key] = result.artifact
        trace.append(
            {
                "agent": rec.key,
                "state": result.state,
                "message": result.message,
                "artifact": result.artifact,
                "artifact_summary": summarize_artifact(result.artifact),
            }
        )

        if result.state == STATE_COMPLETED:
            print(f"[orchestrator] {rec.key} completed.")
            continue
        if result.state in (STATE_INPUT_REQUIRED, STATE_AUTH_REQUIRED):
            question = result.message or "(agent asked for input)"
            print(f"[orchestrator] {rec.key} needs input:\n{question}")
            if auto:
                print("[orchestrator] --auto: treating input-required as failure.")
                _save_run(domain, trace, "", agents)
                return 1
            reply = input("Your reply (empty aborts): ").strip()
            if not reply:
                print("[orchestrator] Aborted by user.")
                _save_run(domain, trace, "", agents)
                return 1
            try:
                followup = await delegate(
                    rec.key,
                    rec.url,
                    text_input=reply,
                    context_id=context_ids.get(rec.key),
                    task_id=_task_id_or_none(result.task),
                    timeout_s=CALL_TIMEOUT_S,
                    poll_interval_s=poll_interval_s,
                )
            except Exception as exc:
                print(f"[orchestrator] Follow-up to {rec.key} failed: {exc}")
                continue
            if followup.context_id:
                context_ids[rec.key] = followup.context_id
            trace.append(
                {
                    "agent": rec.key,
                    "state": followup.state,
                    "message": followup.message,
                    "artifact": followup.artifact,
                    "artifact_summary": summarize_artifact(followup.artifact),
                }
            )
            continue
        if result.state in FAILED_STATES:
            print(
                f"[orchestrator] {rec.key} failed ({result.state}): "
                f"{result.message or 'no message'} — planner will retry or reroute."
            )
            continue
        print(f"[orchestrator] {rec.key} ended in {result.state}; continuing.")

    print(f"[orchestrator] Hit max steps ({max_steps}) without finish.")
    _save_run(domain, trace, "", agents)
    return 1


def _task_id_or_none(task: dict[str, Any]) -> str | None:
    tid = task.get("id")
    return str(tid) if tid else None


def _resolve_data_input(
    data_input: dict[str, Any] | None,
    artifacts: dict[str, Any],
    domain: str,
) -> dict[str, Any] | None:
    """Resolve planner by-reference inputs into full A2A DataParts.

    The planner references large artifacts by id (e.g.
    ``{"opportunity_id": "abc", "domain": "fintech"}``) instead of echoing
    them. This resolves the reference against the stored research artifact
    into the ``{"opportunity": {...}, "domain": ..., "research_notes": ...}``
    shape the Architect agent validates. Anything else passes through.
    """
    if not isinstance(data_input, dict):
        return data_input
    opp_id = data_input.get("opportunity_id")
    if not opp_id:
        return data_input
    research = artifacts.get("research")
    if not isinstance(research, dict):
        raise ValueError("planner referenced opportunity_id with no research artifact yet")
    for opp in research.get("opportunities") or []:
        if isinstance(opp, dict) and str(opp.get("id")) == str(opp_id):
            return {
                "opportunity": opp,
                "domain": data_input.get("domain") or domain,
                "research_notes": opp.get("deep_dive_notes") or "",
            }
    known = [
        str(o.get("id"))
        for o in (research.get("opportunities") or [])
        if isinstance(o, dict)
    ]
    raise ValueError(f"unknown opportunity_id {opp_id!r}; known: {known}")


def _save_run(
    domain: str,
    trace: list[dict[str, Any]],
    summary: str,
    agents: list[AgentRecord],
) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path("runs") / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "result.json"
    out_path.write_text(
        json.dumps(
            {
                "domain": domain,
                "agents": {rec.key: {"url": rec.url, "card": rec.card} for rec in agents},
                "trace": trace,
                "summary": summary,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"[orchestrator] Saved full run to {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dynamic A2A orchestrator: planner delegates via Agent Cards."
    )
    parser.add_argument("--domain", required=True, help="Goal to research/architect")
    parser.add_argument(
        "--agents",
        default=None,
        help="Path to agents.yaml (default: orchestrator/agents.yaml)",
    )
    parser.add_argument("--research-url", default=None)
    parser.add_argument("--architect-url", default=None)
    parser.add_argument(
        "--planner-model",
        default=None,
        help="OpenRouter model id (default: ORCHESTRATOR_MODEL or meta/muse-spark-1.3-contributor)",
    )
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS)
    parser.add_argument(
        "--auto",
        action="store_true",
        help="No input() pauses; input-required tasks fail instead",
    )
    args = parser.parse_args()
    overrides: dict[str, str] = {}
    if args.research_url:
        overrides["research"] = args.research_url
    if args.architect_url:
        overrides["architect"] = args.architect_url
    return asyncio.run(
        _run(
            args.domain,
            args.agents,
            overrides,
            args.max_steps,
            args.auto,
            args.planner_model,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
