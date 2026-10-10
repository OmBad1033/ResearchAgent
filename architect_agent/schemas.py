"""A2A schemas for the Architect Agent.

- ``DesignRequest``: the chosen Opportunity (reuses the Research Agent's
  ``Opportunity`` shape) plus optional research-notes passthrough.
- ``SolutionDesign``: field list exactly per buildPlan Phase 2.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, Field

from research_agent.a2a_schemas import Opportunity


class DesignRequest(BaseModel):
    opportunity: Opportunity
    domain: str = ""
    research_notes: str = ""


class SolutionDesign(BaseModel):
    proposed_stack: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    data_flow_summary: str = ""
    deployment_target: str = ""
    build_effort_estimate: str = ""
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
