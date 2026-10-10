"""Agent registry: MCP-style config + A2A Agent Card discovery.

The orchestrator never hard-codes agent URLs or call order. It loads
``agents.yaml`` (key -> {url, enabled}), fetches each enabled agent's
``/.well-known/agent-card.json``, and hands the cards to the planner,
which decides what to delegate based on skill descriptions.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from orchestrator.a2a_client import fetch_agent_card

DEFAULT_CONFIG_NAME = "agents.yaml"


@dataclass
class AgentRecord:
    key: str
    url: str
    enabled: bool = True
    card: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return str(self.card.get("name") or self.key)

    @property
    def version(self) -> str:
        return str(self.card.get("version") or "?")

    @property
    def description(self) -> str:
        return str(self.card.get("description") or "")

    @property
    def skills(self) -> list[dict[str, Any]]:
        skills = self.card.get("skills") or []
        return [s for s in skills if isinstance(s, dict)]


def default_config_path() -> Path:
    return Path(__file__).resolve().with_name(DEFAULT_CONFIG_NAME)


def load_agents_config(config_path: str | Path) -> list[dict[str, Any]]:
    """Parse agents.yaml into [{key, url, enabled}]. Supports mapping or list shape."""
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"Agents config not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    agents = raw.get("agents") if isinstance(raw, dict) else None
    if agents is None:
        raise ValueError(f"{path} must contain a top-level 'agents' mapping or list")

    entries: list[dict[str, Any]] = []
    if isinstance(agents, dict):
        for key, val in agents.items():
            val = val or {}
            if not isinstance(val, dict):
                raise ValueError(f"agents.{key} must be a mapping with 'url'")
            entries.append(
                {
                    "key": str(key),
                    "url": str(val.get("url") or ""),
                    "enabled": bool(val.get("enabled", True)),
                }
            )
    elif isinstance(agents, list):
        for item in agents:
            if not isinstance(item, dict):
                raise ValueError("agents list entries must be mappings")
            key = item.get("key") or item.get("name")
            if not key or not item.get("url"):
                raise ValueError("each agents entry needs 'key'/'name' and 'url'")
            entries.append(
                {
                    "key": str(key),
                    "url": str(item["url"]),
                    "enabled": bool(item.get("enabled", True)),
                }
            )
    else:
        raise ValueError(f"{path}: 'agents' must be a mapping or a list")

    for entry in entries:
        if not entry["url"]:
            raise ValueError(f"agents.{entry['key']} is missing 'url'")
    return entries


async def discover_agents(
    config_path: str | Path | None = None,
    overrides: dict[str, str] | None = None,
    timeout_s: float = 10.0,
) -> list[AgentRecord]:
    """Load config, apply URL overrides, fetch + cache each enabled Agent Card.

    Raises RuntimeError listing unreachable agents (fail fast, like before).
    """
    path = Path(config_path) if config_path else default_config_path()
    entries = load_agents_config(path)
    overrides = overrides or {}

    records: list[AgentRecord] = []
    failures: list[str] = []
    for entry in entries:
        key = entry["key"]
        url = overrides.get(key) or entry["url"]
        if not entry["enabled"]:
            continue
        try:
            card = await fetch_agent_card(url, timeout_s=timeout_s)
        except Exception as exc:
            failures.append(f"{key} at {url}: {exc}")
            continue
        records.append(AgentRecord(key=key, url=url, card=card))

    if failures:
        raise RuntimeError("Agent discovery failed:\n  " + "\n  ".join(failures))
    if not records:
        raise RuntimeError(f"No enabled agents in {path}")
    return records


def format_agents_for_prompt(agents: list[AgentRecord]) -> str:
    """Compact capability block for the planner prompt."""
    lines: list[str] = []
    for rec in agents:
        lines.append(
            f'- key "{rec.key}" ({rec.name} v{rec.version}) at {rec.url}\n'
            f"  description: {rec.description or '(none)'}"
        )
        if rec.skills:
            for skill in rec.skills:
                sid = skill.get("id") or skill.get("name") or "?"
                sdesc = skill.get("description") or ""
                lines.append(f"  skill {sid}: {sdesc}")
        else:
            lines.append("  skills: (none listed)")
    return "\n".join(lines)
