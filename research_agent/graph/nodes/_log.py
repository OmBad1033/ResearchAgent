"""
Lightweight logging helpers shared by all graph nodes.

Goals:
- Consistent formatting across nodes (header bars, indentation for parallel
  instances, key/value summaries).
- Zero deps — uses print() so it works under plain `python3 main.py`.
- No buffering surprises: flush=True on every print so streaming output
  is visible as nodes complete (important for long-running parallel work).

Public API:
    log_node(node_name, state)           -> returns a context-manager-like
                                              helper for entry/exit pairs.
    log_subagent(node_name, opp_id, ...) -> same shape, indented one level
                                              for parallel sub-graph instances.
"""

from __future__ import annotations

import sys
from typing import Any


_LINE_WIDTH = 70


def _hr(char: str = "=", width: int = _LINE_WIDTH) -> str:
    return char * width


def _truncate(text: str, max_chars: int = 120) -> str:
    """Collapse newlines and cap length for compact log lines."""
    flat = " ".join(text.split())
    if len(flat) <= max_chars:
        return flat
    return flat[: max_chars - 1] + "..."


def _summarize_value(value: Any, max_chars: int = 120) -> str:
    """Render a single state value into a compact loggable string."""
    if isinstance(value, str):
        return _truncate(value, max_chars)
    if isinstance(value, list):
        if not value:
            return "[]"
        # For lists of dicts, show like "[3 items, first=<title>]".
        if isinstance(value[0], dict):
            first_repr = ", ".join(
                f"{k}={_truncate(str(v), 30)}"
                for k, v in list(value[0].items())[:3]
            )
            return f"[{len(value)} items, first={{ {first_repr} }}]"
        return f"[{len(value)} items]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        # For dicts of dicts (e.g. opportunities: {id: Opportunity}), show
        # like "{3 keys, first=<title>}" so the summary mirrors the list branch.
        first_value = next(iter(value.values()))
        if isinstance(first_value, dict):
            first_repr = ", ".join(
                f"{k}={_truncate(str(v), 30)}"
                for k, v in list(first_value.items())[:3]
            )
            return f"{{{len(value)} keys, first={{ {first_repr} }} }}"
        keys = ", ".join(list(value.keys())[:5])
        return f"{{{keys}}}"
    return str(value)


class NodeLogger:
    """Returned by log_node() / log_subagent(). Call .exit(...) when done."""

    def __init__(self, name: str, indent: int = 0):
        self.name = name
        self.indent = indent
        self._prefix = "  " * indent

    def inputs(self, **fields: Any) -> None:
        parts = [f"{k}={_summarize_value(v)}" for k, v in fields.items()]
        print(f"{self._prefix}[{self.name}] in:  {', '.join(parts)}", flush=True)

    def outputs(self, **fields: Any) -> None:
        parts = [f"{k}={_summarize_value(v)}" for k, v in fields.items()]
        print(f"{self._prefix}[{self.name}] out: {', '.join(parts)}", flush=True)

    def info(self, message: str) -> None:
        print(f"{self._prefix}[{self.name}] {message}", flush=True)

    def header(self) -> None:
        print(f"{self._prefix}{_hr('-')}", flush=True)
        print(f"{self._prefix}[{self.name}] running", flush=True)
        print(f"{self._prefix}{_hr('-')}", flush=True)


def log_node(node_name: str, state: dict | None = None) -> NodeLogger:
    """Logger for a top-level graph node."""
    logger = NodeLogger(node_name, indent=0)
    logger.header()
    if state is not None:
        logger.inputs(**_public_state_keys(state))
    return logger


def log_subagent(node_name: str, opp_id: str, state: dict | None = None) -> NodeLogger:
    """Logger for a parallel sub-graph instance. Indented one level."""
    name_with_id = f"{node_name}#{opp_id[:8]}"
    logger = NodeLogger(name_with_id, indent=1)
    logger.header()
    if state is not None:
        logger.inputs(**_public_state_keys(state))
    return logger


def _public_state_keys(state: dict) -> dict:
    """Pick the keys most useful to log; skip large/empty chatter."""
    interesting = ("domain", "hitl_mode", "opportunities", "approved_opportunity_ids",
                   "final_report")
    return {k: state.get(k) for k in interesting if k in state}


def log_stage(stage: str) -> None:
    """A big banner for graph-level transitions (entry, between phases)."""
    print(flush=True)
    print(_hr("="), flush=True)
    print(f"  STAGE: {stage}", flush=True)
    print(_hr("="), flush=True)
    sys.stdout.flush()