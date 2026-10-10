"""A2A schemas for the Research Agent.

Mirrors what the existing graph already produces — no invented fields.
Source of truth for field shapes:

- ``Opportunity`` in ``research_agent/graph/state.py``:
    id, title, description, existing_solutions, deep_dive_notes,
    worth_it_verdict, worth_it_reasoning
- ``worth_it_subagent`` verdict vocabulary:
    "worth pursuing" | "saturated" | "not viable"
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Opportunity(BaseModel):
    id: str
    title: str = ""
    description: str = ""
    existing_solutions: list[str] = Field(default_factory=list)
    deep_dive_notes: str = ""
    worth_it_verdict: str = ""
    worth_it_reasoning: str = ""


class ResearchResult(BaseModel):
    domain: str = ""
    opportunities: list[Opportunity] = Field(default_factory=list)
