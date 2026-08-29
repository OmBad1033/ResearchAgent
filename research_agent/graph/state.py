from typing import TypedDict, Annotated, Literal

from langgraph.graph.message import add_messages


class Opportunity(TypedDict):
    id: str
    title: str
    description: str
    existing_solutions: list[str]
    deep_dive_notes: str
    worth_it_verdict: str  # "worth pursuing" | "saturated" | "not viable"
    worth_it_reasoning: str


def _merge_opportunities_by_id(
    old: dict[str, "Opportunity"],
    new: dict[str, "Opportunity"],
) -> dict[str, "Opportunity"]:
    """Reducer: merge parallel writes into the opportunities dict by Opportunity.id.

    Later writes win for any given id. Existing key insertion order is preserved
    (dict.update on an existing key does not move it), so iteration order matches
    first-discovery order with updates filled in. This contract is what makes
    Send()-style fan-out safe: N parallel sub-agents can each write a one-key
    dict fragment without producing duplicates.
    """
    merged = dict(old)
    merged.update(new)
    return merged


class ResearchState(TypedDict):
    domain: Annotated[str, lambda old, new: new]   # last-write-wins reducer — coalesces parallel writes from subgraphs
    hitl_mode: Literal["human", "ai"]          # set at graph invocation
    opportunities: Annotated[dict[str, Opportunity], _merge_opportunities_by_id]
    approved_opportunity_ids: list[str]
    final_report: str
    messages: Annotated[list, add_messages]     # running transcript