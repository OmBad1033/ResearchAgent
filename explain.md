# Research Agent Backend - Complete LangGraph Explanation

This document explains how the Research Agent backend works, with a focus on LangGraph concepts: graph structure, sub-agent spawning, human-in-the-loop, and backend-to-frontend communication.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [The LangGraph StateGraph](#the-langgraph-stategraph)
3. [State Schema and Reducers](#state-schema-and-reducers)
4. [Node-by-Node Explanation](#node-by-node-explanation)
5. [Sub-Agent Spawning with Send()](#sub-agent-spawning-with-send)
6. [Human-in-the-Loop with interrupt()](#human-in-the-loop-with-interrupt)
7. [Backend-to-Frontend Streaming](#backend-to-frontend-streaming)
8. [Complete Flow Walkthrough](#complete-flow-walkthrough)
9. [Key LangGraph Patterns Used](#key-langgraph-patterns-used)

---

## Architecture Overview

The Research Agent is a **multi-stage research pipeline** built with LangGraph. It:

1. **Discovers opportunities** in a domain (via web search + LLM)
2. **Gets approval** from a human or AI
3. **Deep-dives** into each approved opportunity (parallel execution)
4. **Evaluates** if each opportunity is worth pursuing (parallel execution)
5. **Synthesizes** a final report

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           RESEARCH AGENT FLOW                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   START ──► MANAGER ──► OPPORTUNITY_DISCOVERY ──► MANAGER                │
│                              │                                           │
│                              ▼                                           │
│                     APPROVAL_ROUTER                                      │
│                     ╱           ╲                                        │
│                    ╱             ╲                                       │
│          HUMAN_APPROVAL      AI_APPROVAL                                 │
│                    ╲             ╱                                        │
│                     ╲           ╱                                         │
│                      MANAGER ◄──                                         │
│                         │                                                │
│                         ▼                                                │
│            ┌────────────────────────┐                                   │
│            │   DEEP_DIVE (parallel) │                                   │
│            │   ┌─────┐ ┌─────┐      │                                   │
│            │   │Op A │ │Op B │ ...  │                                   │
│            │   └─────┘ └─────┘      │                                   │
│            └────────────┬───────────┘                                   │
│                         ▼                                                │
│                  ORCHESTRATION ──► MANAGER                               │
│                                      │                                   │
│                                      ▼                                   │
│            ┌────────────────────────┐                                   │
│            │   WORTH_IT (parallel)   │                                   │
│            │   ┌─────┐ ┌─────┐      │                                   │
│            │   │Op A │ │Op B │ ...  │                                   │
│            │   └─────┘ └─────┘      │                                   │
│            └────────────┬───────────┘                                   │
│                         ▼                                                │
│                  ORCHESTRATION ──► MANAGER                               │
│                                      │                                   │
│                                      ▼                                   │
│                                SYNTHESIS                                  │
│                                      │                                   │
│                                      ▼                                   │
│                                    END                                    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## The LangGraph StateGraph

### What is a StateGraph?

A **StateGraph** is LangGraph's core abstraction. It's a graph where:

- **Nodes** are functions that take the current state and return updates
- **Edges** define how control flows between nodes
- **State** is a TypedDict that persists across the entire graph execution

```python
# From graph/builder.py
from langgraph.graph import StateGraph, START, END

graph = StateGraph(ResearchState)  # ResearchState is our state schema
```

### Graph Compilation

Before a graph can run, it must be **compiled**:

```python
from langgraph.checkpoint.memory import InMemorySaver

memory = InMemorySaver()  # Stores state for interrupt/resume
app = graph.compile(checkpointer=memory)
```

**Why the checkpointer matters:**
- Required for `interrupt()` to work (human-in-the-loop)
- Persists state across pauses and resumes
- Uses `thread_id` to scope state per conversation/run

---

## State Schema and Reducers

### The ResearchState TypedDict

```python
# From graph/state.py
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class Opportunity(TypedDict):
    id: str
    title: str
    description: str
    existing_solutions: list[str]
    deep_dive_notes: str
    worth_it_verdict: str  # "worth pursuing" | "saturated" | "not viable"
    worth_it_reasoning: str

class ResearchState(TypedDict):
    domain: Annotated[str, lambda old, new: new]  # last-write-wins
    hitl_mode: Literal["human", "ai"]
    opportunities: Annotated[dict[str, Opportunity], _merge_opportunities_by_id]
    approved_opportunity_ids: list[str]
    final_report: str
    messages: Annotated[list, add_messages]
```

### What are Annotated Reducers?

**Reducers** define how parallel writes merge. When multiple sub-agents write to the same state key simultaneously, LangGraph uses the reducer to combine them.

```python
def _merge_opportunities_by_id(
    old: dict[str, "Opportunity"],
    new: dict[str, "Opportunity"],
) -> dict[str, "Opportunity"]:
    """Merge parallel writes into the opportunities dict by id.
    
    Later writes win for any given id. This is what makes Send() fan-out safe:
    N parallel sub-agents can each write a one-key dict fragment without 
    producing duplicates.
    """
    merged = dict(old)
    merged.update(new)
    return merged
```

**Why this matters for parallel execution:**

Imagine 3 sub-agents running in parallel, each returning:
```python
# Agent 1 returns:
{"opportunities": {"abc": Opportunity(...)}}

# Agent 2 returns:
{"opportunities": {"def": Opportunity(...)}}

# Agent 3 returns:
{"opportunities": {"ghi": Opportunity(...)}}
```

Without a reducer, you'd get 3 separate dicts. With the merge-by-id reducer, they become:
```python
{"opportunities": {"abc": ..., "def": ..., "ghi": ...}}
```

---

## Node-by-Node Explanation

### 1. Manager Node (The Orchestrator)

**Purpose:** Central routing hub that decides which stage runs next.

```python
# From graph/nodes/manager.py
def manager_node(state: ResearchState) -> dict:
    """The manager inspects state and decides the next stage.
    
    Returns an empty dict (no state mutation) - the actual routing
    is done by route_from_manager, wired as a conditional edge.
    """
    stage = _classify_stage(state)
    # ... logging and edge emission ...
    return {}
```

**Stage Classification Logic:**

```python
def _classify_stage(state: ResearchState) -> str:
    opportunities = state.get("opportunities", {})
    approved_ids = state.get("approved_opportunity_ids", [])
    
    # Stage 1: Nothing discovered yet
    if not opportunities:
        return "opportunity_discovery"
    
    # Stage 2: Discovered but not approved
    if "approved_opportunity_ids" not in state:
        return "approval_router"
    
    # Stage 3: Approved but not deep-dived
    if not any(opp.get("deep_dive_notes") for opp in opportunities.values()):
        return "deep_dive"
    
    # Stage 4: Deep-dived but not evaluated
    if not any(opp.get("worth_it_verdict") for opp in opportunities.values()):
        return "worth_it"
    
    # Stage 5: All evaluated, ready for synthesis
    return "synthesis"
```

### 2. Opportunity Discovery Node

**Purpose:** Searches the web for problems/opportunities in the domain.

```python
# From graph/nodes/opportunity_discovery.py
def opportunity_discovery_node(state: ResearchState) -> dict:
    domain = state.get("domain")
    
    # 1. Search Tavily for problems in this domain
    results = search_problems(domain)
    
    # 2. Ask LLM to distill into structured opportunities
    opportunities = llm.invoke([
        {"role": "user", "content": f"Extract opportunities from: {results}"}
    ])
    
    # 3. Return opportunities dict (keyed by id)
    return {"opportunities": {opp["id"]: opp for opp in opportunities}}
```

### 3. Approval Router Node

**Purpose:** Routes to human or AI approval based on `hitl_mode`.

```python
# From graph/builder.py
def _route_after_approval(state: ResearchState) -> str:
    mode = state.get("hitl_mode")
    if mode == "human":
        return "human_approval"
    if mode == "ai":
        return "ai_approval"
    return "human_approval"  # default

graph.add_conditional_edges(
    "approval_router",
    _route_after_approval,
    {
        "human_approval": "human_approval",
        "ai_approval": "ai_approval",
    },
)
```

### 4. Human Approval Node (Human-in-the-Loop)

**Purpose:** Pauses the graph for human review using `interrupt()`.

```python
# From graph/nodes/human_approval.py
from langgraph.types import interrupt

def human_approval_node(state: ResearchState) -> dict:
    opportunities = state.get("opportunities", {})
    
    # PAUSE THE GRAPH - this is the magic
    chosen = interrupt({
        "type": "approval_request",
        "opportunities": opportunities,
        "instructions": "Select opportunities to deep-dive",
    })
    
    # Resume continues here with the user's choice
    approved_ids = chosen.get("approved_ids", [])
    return {"approved_opportunity_ids": approved_ids}
```

**How interrupt() works:**
1. Graph execution pauses at this point
2. The interrupt payload is sent to the caller
3. Caller (frontend) shows UI, collects user input
4. Caller sends resume request with user's choice
5. Graph continues with `chosen` receiving the resume payload

### 5. AI Approval Node

**Purpose:** Uses an LLM to automatically approve opportunities.

```python
# From graph/nodes/ai_approval.py
def ai_approval_node(state: ResearchState) -> dict:
    opportunities = state.get("opportunities", {})
    
    # Ask LLM to pick the best opportunities
    response = llm.invoke([
        {"role": "user", "content": f"Which opportunities are worth pursuing? {opportunities}"}
    ])
    
    approved_ids = parse_llm_response(response)
    return {"approved_opportunity_ids": approved_ids}
```

### 6. Deep Dive Sub-Agent

**Purpose:** Researches one opportunity in depth (runs in parallel).

```python
# From graph/nodes/deep_dive_subagent.py
def deep_dive_subagent(state: dict) -> dict:
    # Extract the single opportunity from the Send() payload
    opps = state.get("opportunities", {})
    opp_id = next(iter(opps))  # The ONLY key in the dict
    opp = opps[opp_id]
    
    # 1. Search for existing solutions
    solutions = search_solutions(opp["title"])
    
    # 2. Analyze market trends via LLM
    trends = llm.invoke([
        {"role": "user", "content": f"Analyze trends for: {opp['title']}"}
    ])
    
    # 3. Return updated opportunity (single-key dict for merge)
    return {
        "opportunities": {
            opp_id: {**opp, "deep_dive_notes": trends, "existing_solutions": solutions}
        }
    }
```

### 7. Worth-It Sub-Agent

**Purpose:** Evaluates if an opportunity is worth pursuing (runs in parallel).

```python
# From graph/nodes/worth_it_subagent.py
def worth_it_subagent(state: dict) -> dict:
    opps = state.get("opportunities", {})
    opp_id = next(iter(opps))
    opp = opps[opp_id]
    
    # Ask LLM for a verdict
    verdict = llm.invoke([
        {"role": "user", "content": f"Is this worth pursuing? {opp}"}
    ])
    
    return {
        "opportunities": {
            opp_id: {**opp, "worth_it_verdict": verdict, "worth_it_reasoning": "..."}
        }
    }
```

### 8. Orchestration Node

**Purpose:** Validates that all parallel sub-agents have completed.

```python
# From graph/nodes/orchestration.py
def orchestration_node(state: ResearchState) -> dict:
    # Fan-in point - all parallel executions merge here
    # We can validate completion, log summaries, etc.
    return {}
```

### 9. Synthesis Node

**Purpose:** Generates the final research report.

```python
# From graph/nodes/synthesis.py
def synthesis_node(state: ResearchState) -> dict:
    opportunities = state.get("opportunities", {})
    
    # Filter to worth-pursuing opportunities
    worth_pursuing = [opp for opp in opportunities.values() 
                       if opp["worth_it_verdict"] == "worth pursuing"]
    
    # Generate final report
    report = llm.invoke([
        {"role": "user", "content": f"Write a research report: {worth_pursuing}"}
    ])
    
    return {"final_report": report}
```

---

## Sub-Agent Spawning with Send()

### What is Send()?

`Send()` is LangGraph's mechanism for **dynamic parallel execution**. It lets you spawn multiple instances of a node, each with different input.

```python
from langgraph.types import Send
```

### How the Manager Spawns Sub-Agents

```python
# From graph/nodes/manager.py
def _build_deep_dive_sends(
    opportunities: dict[str, Opportunity],
    approved_ids: list[str],
    domain: str,
) -> list[Send]:
    """Create one Send() per approved opportunity."""
    sends = []
    for opp_id in approved_ids:
        opp = opportunities.get(opp_id)
        if opp is None:
            continue
        
        # Each Send carries a payload for ONE opportunity
        payload = {
            "opportunities": {opp_id: opp},  # Single-key dict!
            "domain": domain,
        }
        sends.append(Send("deep_dive", payload))
    
    return sends
```

### The Single-Key Dict Pattern

**Critical insight:** The payload MUST use a single-key dict under `opportunities`:

```python
# CORRECT - survives subgraph boundary
payload = {"opportunities": {"abc123": Opportunity(...)}}

# WRONG - gets stripped at boundary
payload = {"title": "...", "description": "..."}  # These aren't state channels!
```

**Why?** LangGraph strips any payload keys that aren't channels on the state schema. The `ResearchState` has an `opportunities` channel, but no `title` or `description` channels.

### Sub-Graph Structure

Each sub-agent is wrapped in a sub-graph:

```python
# From graph/subgraphs/deep_dive_graph.py
from langgraph.graph import StateGraph, START, END

def build_deep_dive_subgraph() -> StateGraph:
    subgraph = StateGraph(ResearchState)  # Same schema as parent!
    
    subgraph.add_node("deep_dive_subagent", deep_dive_subagent)
    subgraph.add_edge(START, "deep_dive_subagent")
    subgraph.add_edge("deep_dive_subagent", END)
    
    return subgraph

# Compile and add to main graph
deep_dive_subgraph = build_deep_dive_subgraph().compile()
graph.add_node("deep_dive", deep_dive_subgraph)
```

### Fan-Out and Fan-In

```
                    ┌─────────────────┐
                    │    MANAGER      │
                    │  (builds Sends) │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
        ┌─────────┐   ┌─────────┐   ┌─────────┐
        │Send(A)  │   │Send(B)  │   │Send(C)  │
        └────┬────┘   └────┬────┘   └────┬────┘
             │             │             │
             ▼             ▼             ▼
        ┌─────────┐   ┌─────────┐   ┌─────────┐
        │deep_dive│   │deep_dive│   │deep_dive│
        │  (A)    │   │  (B)    │   │  (C)    │
        └────┬────┘   └────┬────┘   └────┬────┘
             │             │             │
             └──────────────┼──────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ ORCHESTRATION │
                    │   (fan-in)    │
                    └───────────────┘
```

**LangGraph automatically:**
1. Runs all `Send()` instances in parallel
2. Waits for all to complete
3. Merges results via the reducer
4. Continues to the next node (orchestration)

---

## Human-in-the-Loop with interrupt()

### The interrupt() Function

```python
from langgraph.types import interrupt

def human_approval_node(state: ResearchState) -> dict:
    # Pause execution
    chosen = interrupt({
        "type": "approval_request",
        "opportunities": state.get("opportunities", {}),
    })
    
    # Execution resumes here after caller provides input
    return {"approved_opportunity_ids": chosen.get("approved_ids", [])}
```

### How interrupt() Works Internally

1. **Graph pauses:** Execution stops at the `interrupt()` call
2. **Payload surfaces:** The interrupt argument appears in the stream as `__interrupt__`
3. **State persisted:** Checkpointer saves current state
4. **Caller notified:** Backend detects interrupt and parks
5. **Resume requested:** Caller sends `Command(resume=payload)`
6. **Graph continues:** `interrupt()` returns the resume payload

### Backend Handling of Interrupts

```python
# From api/runner.py
async def _drain_iteration(...):
    async for mode, payload in app.astream(input_or_command, config=config, stream_mode=["custom", "updates"]):
        if mode == "updates":
            # Check for interrupt
            if "__interrupt__" in payload:
                interrupt_payload = payload["__interrupt__"]
                continue  # Stop processing, will raise _GraphPaused
    
    if interrupt_payload is not None:
        raise _GraphPaused(interrupt_payload)  # Signal to driver
```

### Resume Flow

```python
# From api/runner.py
async def _drive():
    # First pass - runs until interrupt
    try:
        await _drain_iteration(config, initial_input, ...)
    except _GraphPaused:
        pass  # Graph is paused, waiting for resume
    
    # Park until /resume endpoint is called
    payload = await handle.wait_for_resume()
    
    # Second pass - continues from interrupt
    await _drain_iteration(config, Command(resume=payload), ...)
```

### HTTP Resume Endpoint

```python
# From api/server.py
@app.post("/runs/{run_id}/resume")
async def resume_endpoint(run_id: str, body: ResumeRequest):
    handle = get_handle(run_id)
    
    # Wake up the parked runner
    handle.request_resume({"approved_ids": body.approved_opportunity_ids})
    
    return {"status": "accepted"}
```

### Frontend Integration

```typescript
// Frontend WebSocket handler
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === "node_status" && data.node_id === "human_approval" && data.status === "running") {
    // Show approval UI
    showApprovalDialog(data.summary);
  }
};

// When user submits approval
async function submitApproval(approvedIds: string[]) {
  await fetch(`/runs/${runId}/resume`, {
    method: "POST",
    body: JSON.stringify({ approved_opportunity_ids: approvedIds }),
  });
}
```

---

## Backend-to-Frontend Streaming

### WebSocket Endpoint

```python
# From api/server.py
@app.websocket("/ws/{run_id}")
async def ws_endpoint(websocket: WebSocket, run_id: str):
    await websocket.accept()
    
    # Receive initial config
    start_msg = await websocket.receive_json()
    domain = start_msg.get("domain")
    hitl_mode = start_msg.get("hitl_mode")
    
    # Create event writer for this run
    writer = EventWriter(run_id)
    
    # Start graph execution
    await start_run(run_id=run_id, domain=domain, hitl_mode=hitl_mode, writer=writer)
    
    # Stream events to frontend
    async for event in writer.subscribe():
        await websocket.send_json(event)
```

### EventWriter (Pub/Sub Pattern)

```python
# From api/event_writer.py
class EventWriter:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self._subscribers: list[asyncio.Queue] = []
        self._early_events: list[dict] = []  # Buffer for race conditions
    
    def emit(self, event: dict) -> None:
        """Called by nodes to send events to frontend."""
        if not self._subscribers:
            # Buffer if no subscriber yet
            self._early_events.append(event)
            return
        
        for queue in self._subscribers:
            queue.put_nowait(event)
    
    async def subscribe(self):
        """WebSocket handler calls this to receive events."""
        queue = asyncio.Queue()
        self._subscribers.append(queue)
        
        # Replay buffered events
        for event in self._early_events:
            queue.put_nowait(event)
        self._early_events.clear()
        
        while True:
            event = await queue.get()
            yield event
            if event.get("type") == "run_completed":
                break
```

### Streaming Modes

The runner uses hybrid streaming:

```python
# From api/runner.py
async for mode, payload in app.astream(
    input_or_command,
    config=config,
    stream_mode=["custom", "updates"],
):
    if mode == "custom":
        # Custom events from get_stream_writer()
        # Used for: node_added, edge_active, run_completed
        ...
    
    elif mode == "updates":
        # State updates from nodes
        # Used for: node_status (running/completed)
        ...
```

### Event Types (Per CONTRACT.md)

```python
# From api/__init__.py

# 1. node_added - A new node appeared in the graph
{
    "type": "node_added",
    "run_id": "abc123",
    "node_id": "deep_dive_abc",
    "node_type": "deep_dive_subagent",
    "parent_id": "deep_dive",
    "label": "AI-powered Code Review",
    "opportunity_id": "abc",
    "timestamp": "2024-01-15T10:30:00Z"
}

# 2. node_status - Node lifecycle update
{
    "type": "node_status",
    "run_id": "abc123",
    "node_id": "deep_dive_abc",
    "status": "running",  # or "completed", "error"
    "summary": "Searching for existing solutions",
    "timestamp": "2024-01-15T10:30:01Z"
}

# 3. edge_active - Control flow between nodes
{
    "type": "edge_active",
    "run_id": "abc123",
    "from": "manager",
    "to": "deep_dive",
    "timestamp": "2024-01-15T10:30:00Z"
}

# 4. run_completed - Graph finished
{
    "type": "run_completed",
    "run_id": "abc123",
    "timestamp": "2024-01-15T10:35:00Z"
}
```

### How Nodes Emit Events

```python
# From graph/nodes/manager.py
from langgraph.config import get_stream_writer
from api import emit_node_added, emit_edge_active

def manager_node(state: ResearchState) -> dict:
    writer = get_stream_writer()
    run_id = get_config().get("configurable", {}).get("run_id")
    
    # Emit node_added for each parallel instance BEFORE Send()
    for opp_id, opp in opportunities.items():
        emit_node_added(
            writer,
            run_id=run_id,
            node_id=f"deep_dive_{opp_id}",
            node_type="deep_dive_subagent",
            parent_id="deep_dive",
            label=opp["title"],
            opportunity_id=opp_id,
        )
    
    # Emit edge for the routing decision
    emit_edge_active(writer, run_id=run_id, from_node="manager", to_node="deep_dive")
    
    return {}
```

---

## Complete Flow Walkthrough

Let's trace a complete execution from start to finish.

### Step 1: WebSocket Connection

```
Frontend                          Backend
   │                                 │
   │──── WebSocket /ws/abc123 ─────►│
   │                                 │
   │◄─── accept ────────────────────│
   │                                 │
   │──── {"domain": "fintech", ────►│
   │      "hitl_mode": "human"}      │
   │                                 │
```

### Step 2: Graph Start

```
Backend creates initial state:
{
    "domain": "fintech",
    "hitl_mode": "human",
    "opportunities": {},
    "approved_opportunity_ids": [],
    "final_report": "",
    "messages": []
}

Emits events:
- node_added: manager
- node_added: opportunity_discovery
- node_added: approval_router
- node_added: human_approval
- ... (all static nodes)
- node_status: manager (running)
- edge_active: manager → opportunity_discovery
- node_status: opportunity_discovery (running)
```

### Step 3: Opportunity Discovery

```
opportunity_discovery_node:
  1. Calls search_problems("fintech") via Tavily
  2. Sends results to Bedrock LLM
  3. LLM returns structured opportunities

Returns:
{
    "opportunities": {
        "abc": {id: "abc", title: "AI Underwriting", ...},
        "def": {id: "def", title: "Fraud Detection", ...},
        "ghi": {id: "ghi", title: "Credit Scoring", ...}
    }
}

Emits:
- node_status: opportunity_discovery (completed)
- edge_active: opportunity_discovery → manager
- node_status: manager (running)
```

### Step 4: Approval Routing

```
manager_node classifies stage → "approval_router"

Emits:
- edge_active: manager → approval_router
- node_status: approval_router (running)

approval_router_node inspects hitl_mode → "human"

Emits:
- edge_active: approval_router → human_approval
- node_status: human_approval (running)
- node_status: human_approval (running, summary: "Waiting for approval")
```

### Step 5: Human-in-the-Loop

```
human_approval_node calls interrupt({...})

Backend detects __interrupt__ in stream
Runner parks, waiting for /resume

Frontend shows approval UI with opportunities:
  1. [abc] AI Underwriting
  2. [def] Fraud Detection  
  3. [ghi] Credit Scoring

User selects: [abc, def]

Frontend POSTs to /runs/abc123/resume:
{
    "approved_opportunity_ids": ["abc", "def"]
}

Backend calls Command(resume={"approved_ids": ["abc", "def"]})

interrupt() returns: {"approved_ids": ["abc", "def"]}

human_approval_node returns:
{
    "approved_opportunity_ids": ["abc", "def"]
}
```

### Step 6: Deep Dive Fan-Out

```
manager_node classifies stage → "deep_dive"
manager_node builds Sends:
  - Send("deep_dive", {"opportunities": {"abc": {...}}, "domain": "fintech"})
  - Send("deep_dive", {"opportunities": {"def": {...}}, "domain": "fintech"})

Emits:
- node_added: deep_dive_abc (parent: deep_dive)
- node_added: deep_dive_def (parent: deep_dive)
- edge_active: manager → deep_dive
- node_status: deep_dive_abc (running)
- node_status: deep_dive_def (running)

Both sub-agents run IN PARALLEL:
  - deep_dive_abc: search_solutions("AI Underwriting") + LLM trends
  - deep_dive_def: search_solutions("Fraud Detection") + LLM trends

Each returns:
{
    "opportunities": {
        "abc": {..., "deep_dive_notes": "...", "existing_solutions": [...]}
    }
}

Reducer merges:
{
    "opportunities": {
        "abc": {..., "deep_dive_notes": "..."},
        "def": {..., "deep_dive_notes": "..."}
    }
}
```

### Step 7: Fan-In to Orchestration

```
Both deep_dive instances complete

Emits:
- node_status: deep_dive_abc (completed)
- node_status: deep_dive_def (completed)
- edge_active: deep_dive → orchestration
- node_status: orchestration (running)

orchestration_node validates completion, returns {}

Emits:
- node_status: orchestration (completed)
- edge_active: orchestration → manager
```

### Step 8: Worth-It Fan-Out

```
manager_node classifies stage → "worth_it"
manager_node builds Sends for deep-dived opportunities

Emits:
- node_added: worth_it_abc
- node_added: worth_it_def
- edge_active: manager → worth_it
- node_status: worth_it_abc (running)
- node_status: worth_it_def (running)

Both sub-agents run IN PARALLEL, each returns verdict

Reducer merges verdicts into opportunities
```

### Step 9: Synthesis

```
manager_node classifies stage → "synthesis"

Emits:
- edge_active: manager → synthesis
- node_status: synthesis (running)

synthesis_node:
  1. Filters opportunities with verdict "worth pursuing"
  2. Calls LLM to generate final report
  3. Returns {"final_report": "..."}

Emits:
- node_status: synthesis (completed)
- run_completed
```

### Step 10: WebSocket Close

```
Frontend receives run_completed
WebSocket connection closes
```

---

## Key LangGraph Patterns Used

### 1. StateGraph with TypedDict

```python
class ResearchState(TypedDict):
    domain: str
    opportunities: dict[str, Opportunity]
    ...
```

**Why:** Type safety, IDE support, clear contract between nodes.

### 2. Annotated Reducers for Parallel Writes

```python
opportunities: Annotated[dict[str, Opportunity], _merge_opportunities_by_id]
```

**Why:** Enables safe parallel execution with automatic merging.

### 3. Conditional Edges for Routing

```python
graph.add_conditional_edges(
    "manager",
    route_from_manager,
    {
        "opportunity_discovery": "opportunity_discovery",
        "approval_router": "approval_router",
        ...
    },
)
```

**Why:** Dynamic routing based on state inspection.

### 4. Send() for Dynamic Parallel Execution

```python
sends = [Send("deep_dive", {"opportunities": {id: opp}}) for id in approved_ids]
```

**Why:** Spawn N instances at runtime, not compile time.

### 5. Sub-Graphs as Nodes

```python
subgraph = StateGraph(ResearchState)
subgraph.add_node("inner", inner_node)
graph.add_node("wrapper", subgraph.compile())
```

**Why:** Encapsulate complex logic, enable parallel execution of sub-workflows.

### 6. interrupt() for Human-in-the-Loop

```python
chosen = interrupt({"type": "approval_request", ...})
```

**Why:** Pause graph, collect human input, resume seamlessly.

### 7. Checkpointer for State Persistence

```python
memory = InMemorySaver()
app = graph.compile(checkpointer=memory)
```

**Why:** Required for interrupt/resume, enables state inspection.

### 8. Hybrid Streaming

```python
async for mode, payload in app.astream(..., stream_mode=["custom", "updates"]):
    if mode == "custom":
        # Handle custom events
    elif mode == "updates":
        # Handle state updates
```

**Why:** Get both custom events (for UI) and state updates (for lifecycle).

### 9. get_stream_writer() for Custom Events

```python
from langgraph.config import get_stream_writer

writer = get_stream_writer()
writer({"type": "node_added", ...})
```

**Why:** Emit custom events mid-execution for real-time UI updates.

### 10. Command(resume=...) for Resuming

```python
from langgraph.types import Command

await app.astream(Command(resume=payload), config=config)
```

**Why:** Resume from interrupt with user input.

---

## Summary

The Research Agent demonstrates several advanced LangGraph patterns:

| Pattern | Purpose | Implementation |
|---------|---------|----------------|
| **StateGraph** | Define workflow structure | `StateGraph(ResearchState)` |
| **Reducers** | Merge parallel writes | `Annotated[dict, merge_by_id]` |
| **Conditional Edges** | Dynamic routing | `add_conditional_edges()` |
| **Send()** | Parallel execution | `Send("node", payload)` |
| **Sub-Graphs** | Encapsulate sub-workflows | `subgraph.compile()` as node |
| **interrupt()** | Human-in-the-loop | `interrupt(payload)` |
| **Checkpointer** | Persist state | `InMemorySaver()` |
| **Streaming** | Real-time updates | `astream(stream_mode=[...])` |
| **Custom Events** | UI updates | `get_stream_writer()` |
| **Resume** | Continue after interrupt | `Command(resume=payload)` |

The key insight is that LangGraph provides primitives for building **stateful, multi-agent workflows** with:
- Clear state management (TypedDict + reducers)
- Dynamic control flow (conditional edges + Send)
- Human collaboration (interrupt + resume)
- Real-time observability (streaming + custom events)

This architecture scales from simple linear flows to complex parallel multi-agent systems while maintaining clarity and debuggability.
