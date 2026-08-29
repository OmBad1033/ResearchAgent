"""
Entry point for running the research agent graph.

Two modes:

    python main.py --mode ai --domain fintech
        Autonomous run. Picks opportunities via Xiaomi MiMo, deep-dives
        and worth-it-evaluates them, prints the final report.

    python main.py --mode human --domain elder-care
        Pauses for human approval of discovered opportunities. You'll
        be prompted (via stdin) to type comma-separated IDs, or "all"
        to approve everything.

A stable `thread_id` is passed at invoke() time so the in-memory
checkpointer can persist state across the interrupt() pause when
running in human mode.
"""

import argparse
import re
import sys
from pathlib import Path
from uuid import uuid4

from langgraph.types import Command

from graph.builder import app


def _slugify_topic(domain: str) -> str:
    """Turn a user-supplied domain into a filesystem-safe folder name.

    Examples:
        'fintech'         -> 'fintech'
        'elder care'      -> 'elder-care'
        'AI / ML Ops'     -> 'ai-ml-ops'
    """
    slug = domain.lower().strip()
    # Collapse anything non-alphanumeric into a single dash.
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "untitled"


def _save_report(domain: str, report: str) -> Path:
    """Write the final report to Result/{topic-slug}/report.md.

    Creates the directory if it doesn't exist. Overwrites any existing
    report.md at the same path — each run is a clean snapshot, no
    history stacking.
    """
    out_dir = Path("Result") / _slugify_topic(domain)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "report.md"
    out_path.write_text(report, encoding="utf-8")
    return out_path


def _run_ai_mode(domain: str) -> None:
    """Single invoke — no human in the loop."""
    thread_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print(f"[ai mode] Running autonomous research on '{domain}'...")
    print(f"[ai mode] thread_id = {thread_id}\n")

    result = app.invoke(
        {"domain": domain, "hitl_mode": "ai"},
        config=config,
    )

    report = result.get("final_report", "(no report generated)")
    out_path = _save_report(domain, report)

    print("\n" + "=" * 70)
    print("FINAL REPORT")
    print("=" * 70)
    print(report)
    print(f"\n[ai mode] Saved to {out_path}")


def _run_human_mode(domain: str) -> None:
    """Invoke, handle the interrupt, resume, repeat until done."""
    thread_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print(f"[human mode] Starting research on '{domain}'...")
    print(f"[human mode] thread_id = {thread_id}\n")

    # Initial invoke — graph will run up to interrupt() in human_approval.
    result = app.invoke(
        {"domain": domain, "hitl_mode": "human"},
        config=config,
    )

    # Loop because the graph might pause multiple times (one interrupt per
    # stage that uses it). For this project's topology there's only one
    # interrupt point (human_approval), but the loop handles either case.
    while True:
        interrupts = result.get("__interrupt__")
        if not interrupts:
            break

        # Take the most recent interrupt payload.
        interrupt_obj = interrupts[-1] if isinstance(interrupts, list) else interrupts
        payload = getattr(interrupt_obj, "value", interrupt_obj)

        # Display the opportunities and prompt for input.
        # The interrupt payload carries the same {id: Opportunity} dict shape
        # as state (see human_approval.py). Iterate .values() in insertion
        # order to match what the user saw during discovery.
        opportunities = payload.get("opportunities", {})
        print(f"\n=== Approval needed: {len(opportunities)} opportunities in '{domain}' ===")
        for i, opp in enumerate(opportunities.values(), start=1):
            print(
                f"  {i}. [{opp.get('id', '????')}] {opp.get('title', '(untitled)')}\n"
                f"     {opp.get('description', '')}"
            )
        print(
            "\nEnter comma-separated IDs to approve (e.g. `abc12345,f6a8c2`), "
            "or `all` to approve everything, or `none` to approve nothing:"
        )
        try:
            user_input = input("> ").strip()
        except EOFError:
            user_input = "none"

        if user_input.lower() == "all":
            approved_ids = ["__all__"]
        elif user_input.lower() in ("none", ""):
            approved_ids = []
        else:
            approved_ids = [s.strip() for s in user_input.split(",") if s.strip()]

        result = app.invoke(
            Command(resume={"approved_ids": approved_ids}),
            config=config,
        )

    report = result.get("final_report", "(no report generated)")
    out_path = _save_report(domain, report)

    print("\n" + "=" * 70)
    print("FINAL REPORT")
    print("=" * 70)
    print(report)
    print(f"\n[human mode] Saved to {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the research agent.")
    parser.add_argument(
        "--mode",
        choices=["ai", "human"],
        required=True,
        help="ai = autonomous, human = pause for approval",
    )
    parser.add_argument(
        "--domain",
        required=True,
        help="Domain to research (e.g. 'fintech', 'elder care')",
    )
    args = parser.parse_args()

    if args.mode == "ai":
        _run_ai_mode(args.domain)
    else:
        _run_human_mode(args.domain)

    return 0


if __name__ == "__main__":
    sys.exit(main())