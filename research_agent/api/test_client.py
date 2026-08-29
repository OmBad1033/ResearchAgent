"""
Test client — connects to the FastAPI bridge over a raw `websockets`
connection, sends the session-start frame, and prints every event it
receives. Designed for verifying the event sequence and shape against
CONTRACT.md before the frontend exists.

Usage:
    python -m research_agent.api.test_client --domain fintech
    python -m research_agent.api.test_client --domain fintech --hitl-mode human
    python -m research_agent.api.test_client --run-id my-test --no-resume

Options:
    --host HOST         Backend host (default: localhost)
    --port PORT         Backend port (default: 8000)
    --run-id RUN_ID     run_id / thread_id (default: random uuid4 hex)
    --domain DOMAIN     domain to research (default: fintech)
    --hitl-mode MODE    "ai" or "human" (default: ai)
    --resume            After pause, POST /resume with a hardcoded
                        approval list so the run can complete (default:
                        only meaningful with --hitl-mode human)
    --resume-ids IDS    Comma-separated opportunity ids to approve.
                        If empty, approves none.
    --timeout SECONDS   Stop after N seconds of no events (default: 300)

The client exits when it sees a `run_completed` event, or after the
timeout. Each event is printed as a single JSON line so it's easy to
diff against CONTRACT.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from uuid import uuid4

import websockets


async def run(args: argparse.Namespace) -> int:
    uri = f"ws://{args.host}:{args.port}/ws/{args.run_id}"
    print(f"[test-client] connecting to {uri}", file=sys.stderr)

    approved_ids: list[str] = args.resume_ids or []

    async with websockets.connect(
        uri,
        open_timeout=10,
        # Origin header so the CORS middleware doesn't reject this
        # non-browser client. Real browsers send it automatically.
        origin=f"http://localhost:5173",
    ) as ws:
        # Send the session-start frame.
        await ws.send(json.dumps({"domain": args.domain, "hitl_mode": args.hitl_mode}))
        print(f"[test-client] sent: domain={args.domain!r} hitl_mode={args.hitl_mode!r}", file=sys.stderr)

        saw_completed = False
        paused = False

        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=args.timeout)
            except asyncio.TimeoutError:
                print(f"[test-client] timeout after {args.timeout}s with no events", file=sys.stderr)
                return 1
            except websockets.ConnectionClosed:
                print("[test-client] connection closed by server", file=sys.stderr)
                break

            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[test-client] non-JSON frame: {raw!r}", file=sys.stderr)
                continue

            # Print the event as one JSON line (lets the user grep / diff).
            print(json.dumps(event, sort_keys=True))

            event_type = event.get("type")
            if event_type == "run_completed":
                saw_completed = True
                break
            if event_type == "node_status":
                # Detect the human_approval pause: a running event on
                # the human_approval node marks the moment we should
                # POST /resume (if --resume was passed).
                if (
                    args.hitl_mode == "human"
                    and event.get("node_id") == "human_approval"
                    and event.get("status") == "running"
                    and not paused
                ):
                    paused = True
                    if args.resume:
                        await _post_resume(args, approved_ids)
                    else:
                        print(
                            "[test-client] detected pause; pass --resume to auto-resume",
                            file=sys.stderr,
                        )

    return 0 if saw_completed else 1


async def _post_resume(args: argparse.Namespace, approved_ids: list[str]) -> None:
    """POST to /runs/{run_id}/resume using stdlib HTTP."""
    import urllib.request

    url = f"http://{args.host}:{args.port}/runs/{args.run_id}/resume"
    body = json.dumps({"approved_opportunity_ids": approved_ids}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(
                f"[test-client] POST /resume -> {resp.status}: {resp.read().decode()}",
                file=sys.stderr,
            )
    except Exception as exc:
        print(f"[test-client] POST /resume failed: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bridge test client")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--run-id", default=uuid4().hex)
    parser.add_argument("--domain", default="fintech")
    parser.add_argument("--hitl-mode", choices=["ai", "human"], default="ai")
    parser.add_argument("--resume", action="store_true", help="POST /resume on human pause")
    parser.add_argument("--resume-ids", default="", help="Comma-separated opportunity ids to approve")
    parser.add_argument("--timeout", type=float, default=300.0, help="Per-event timeout in seconds")
    args = parser.parse_args()
    args.resume_ids = [s.strip() for s in args.resume_ids.split(",") if s.strip()]
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
