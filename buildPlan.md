# Build Plan: Architect Agent + A2A Wiring

## 0. Assumptions (flag these if wrong)

- Language/runtime: **Python 3.11+**
- A2A implementation: official `a2a-sdk` (pip package), synchronous `message/send` only — no streaming, no push notifications, no auth, in this first pass.
- The existing Research Agent's code (whatever function/class currently does the research + tagging) is treated as a black box to be *wrapped*, not rewritten.
- LLM calls are provider-agnostic — reuse whatever client/wrapper the Research Agent already uses for the Architect Agent, rather than introducing a new provider.
- Everything runs locally as two separate processes on two ports. No database — results are written to local JSON files for now.
- The human-in-the-loop "pick one opportunity" step is a simple CLI prompt in the orchestrator script, not a UI, for this phase.

If any of these are wrong for the actual repo, stop and ask before proceeding, rather than guessing.

---

## 1. Goal / definition of done

By the end of this plan, running `python orchestrator/[run.py](http://run.py) --domain "..."` should:

1. Call the Research Agent (now running as an A2A server) with the given domain.
2. Print the returned opportunities (worth-solving vs. saturated) with index numbers.
3. Prompt the human to pick one opportunity by number.
4. Send that opportunity (plus its research notes) to the Architect Agent (a new A2A server).
5. Print and save the returned architecture/design artifact to `runs/<timestamp>/result.json`.

Both agents must be independently reachable and correctly discoverable via their Agent Cards (`GET /.well-known/agent-card.json`), and both must always terminate tasks in a terminal state (`completed` or `failed`) — never leave a task hanging in `working`.

---

## 2. Target repo layout

```
project_root/
├── research_agent/
│   ├── agent.py            # EXISTING research logic — do not rewrite, just wrap
│   ├── executor.py          # NEW: AgentExecutor adapter around agent.py
│   ├── server.py             # NEW: A2A server entrypoint (Agent Card + JSON-RPC)
│   └── schemas.py            # NEW: pydantic models for the opportunities artifact
│
├── architect_agent/
│   ├── agent.py              # NEW: takes one opportunity, produces a design
│   ├── executor.py           # NEW: AgentExecutor adapter around agent.py
│   ├── server.py              # NEW: A2A server entrypoint
│   └── schemas.py             # NEW: pydantic models for input + output artifacts
│
├── orchestrator/
│   └── run.py                  # NEW: CLI script chaining both agents + human step
│
├── runs/                        # NEW: output directory, one folder per run
├── requirements.txt
└── README.md                     # NEW: how to run everything locally

```

---

## 3. Phase 1 — Wrap the existing Research Agent as an A2A server

**Do not touch the internals of the existing research logic.** Just wrap it.

Tasks:

1. Read the existing research agent code to determine its current function signature, inputs, and output shape (what fields it currently returns for each opportunity — title, description, worth-solving/saturated tag, any supporting notes).
2. Define [`schemas.py`](http://schemas.py): a pydantic model `Opportunity` (fields matching what the existing code already produces — don't invent fields it doesn't have) and `ResearchResult` (a list of `Opportunity`).
3. Define the Agent Card in [`server.py`](http://server.py): 
  ```json
  {  "name": "Research Agent",  "description": "Extracts and evaluates business opportunities/problem statements for a given domain",  "version": "0.1.0",  "skills": [    {      "id": "research_opportunities",      "name": "Research Opportunities",      "description": "Given a domain or problem statement, returns candidate opportunities tagged worth-solving or saturated",      "tags": ["research"]    }  ],  "capabilities": { "streaming": false }}
  
  ```
4. Implement [`executor.py`](http://executor.py): a class subclassing the SDK's `AgentExecutor` whose `execute()` method:
  - Reads the input `TextPart` (the domain/problem statement) from the incoming message.
  - Calls the existing research agent function.
  - Wraps the result as a `DataPart` conforming to `ResearchResult`.
  - Emits the artifact and marks the task `completed`.
  - On any exception, marks the task `failed` with the error message — never lets an unhandled exception hang the task.
5. Implement [`server.py`](http://server.py): wire the executor into the SDK's request handler and Starlette app, run on a fixed local port (e.g. `8001`).
6. **Test before moving on:**
  - `curl localhost:8001/.well-known/agent-card.json` returns the card.
  - Send a manual `message/send` request with a sample domain and confirm a valid `ResearchResult` artifact comes back.
  - Send an intentionally malformed request and confirm the task fails cleanly instead of crashing the server.

---

## 4. Phase 2 — Build the Architect Agent

Tasks:

1. Define [`schemas.py`](http://schemas.py):
  - Input: `DesignRequest` — the chosen `Opportunity` plus any research notes.
  - Output: `SolutionDesign` with fields:
    - `proposed_stack: list[str]`
    - `components: list[str]`
    - `data_flow_summary: str`
    - `deployment_target: str`
    - `build_effort_estimate: str`
    - `risks: list[str]`
    - `open_questions: list[str]`
2. Implement [`agent.py`](http://agent.py): a single well-structured LLM call (use the same LLM client/provider the research agent already uses) that takes a `DesignRequest` and returns a `SolutionDesign`, using structured/JSON output mode so the response reliably parses into the schema. Keep the prompt focused: "given this specific problem statement and why it's worth solving, propose one sensible, buildable architecture — don't hedge with multiple options unless asked."
3. Define the Agent Card: 
  ```json
  {  "name": "Architect Agent",  "description": "Designs a solution architecture for a given problem statement",  "version": "0.1.0",  "skills": [    {      "id": "design_solution",      "name": "Design Solution",      "description": "Given a problem statement and research context, proposes an architecture and build approach",      "tags": ["architecture", "design"]    }  ],  "capabilities": { "streaming": false }}
  
  ```
4. Implement [`executor.py`](http://executor.py) following the same pattern as the research agent's (parse input parts → call [`agent.py`](http://agent.py) → emit `DataPart` artifact → mark `completed`; on error, mark `failed`).
5. Implement [`server.py`](http://server.py), run on a different fixed local port (e.g. `8002`).
6. **Test before moving on:**
  - Agent Card reachable at `localhost:8002/.well-known/agent-card.json`.
  - Send a hand-crafted sample `DesignRequest` directly (not yet via the orchestrator) and confirm a valid, schema-conforming `SolutionDesign` artifact comes back.
  - Send a malformed/incomplete request and confirm graceful `failed` state.

---

## 5. Phase 3 — Orchestrator script

Tasks:

1. Implement `orchestrator/[run.py](http://run.py)`:
  - Accepts `--domain` as a CLI argument.
  - Uses an A2A client (the SDK's client helper, or plain HTTP + JSON-RPC if the SDK's client is awkward to use standalone) to call the Research Agent's `research_opportunities` skill at `localhost:8001`.
  - Parses the returned `ResearchResult` and prints each opportunity with an index number, its worth-solving/saturated tag, and a short description.
  - Prompts the human via `input()`: "Pick an opportunity to architect (number):"
  - Sends the chosen `Opportunity` (with its notes) as a `DesignRequest` to the Architect Agent's `design_solution` skill at `localhost:8002`.
  - Prints the returned `SolutionDesign` in readable form.
  - Writes the full run (domain, all opportunities, chosen opportunity, resulting design) to `runs/<timestamp>/result.json`.
2. **Test before moving on:** run the full script end-to-end against both live local servers with a real sample domain and confirm the output file is written correctly.

---

## 6. Phase 4 — Error handling &amp; task lifecycle correctness

Tasks:

1. Confirm both executors *always* reach a terminal task state, including when the LLM call raises, times out, or returns unparseable output.
2. Add a client-side timeout in the orchestrator for each A2A call (e.g. 60s) so a hung agent doesn't hang the whole script.
3. Add basic input validation in the Architect Agent: if the incoming `DesignRequest` is missing required fields, fail the task with a clear error message rather than passing bad data to the LLM.

---

## 7. Phase 5 — Optional / only if time allows

Do not start this until Phases 1–4 are working end-to-end.

- Add streaming (`message/stream`) to the Architect Agent so the orchestrator can show progress on longer design generations.
- Add a lightweight FastAPI wrapper around the orchestrator so it can be called from a web frontend instead of the CLI (relevant if/when the earlier frontend plan gets built).

---

## 8. Testing checklist (final acceptance)

- [ ] `GET /.well-known/agent-card.json` works for both agents
- [ ] Research Agent returns a valid, schema-conforming artifact for a sample domain
- [ ] Architect Agent returns a valid, schema-conforming artifact for a sample opportunity
- [ ] Orchestrator runs end-to-end against both live servers, human selection works
- [ ] Malformed input to either agent results in a `failed` task, not a crash
- [ ] No task is ever left in `working` state indefinitely
- [ ] `runs/<timestamp>/result.json` is written with the full record of a run

---

## 9. Prompt to give your coding agent

Paste the following, along with this plan file, to your coding agent:

```
Follow the attached build plan (Build Plan: Architect Agent + A2A Wiring)
phase by phase, in order. Before Phase 1, read the existing research agent
code to confirm its actual function signature and output shape, and adjust
schemas.py to match reality rather than the plan's guesses if there's a
mismatch.

After each phase, run the "test before moving on" steps listed for that
phase and show me the output before continuing to the next phase. Do not
skip ahead to a later phase if an earlier phase's tests aren't passing.

Do not modify the existing research agent's core logic — only wrap it.
Do not add authentication, streaming, or a database — those are explicitly
out of scope until Phase 5, and only if I ask for them.

If you hit a decision not covered by the plan (e.g. exact field names in the
existing research agent's output), stop and ask me rather than guessing
silently.

```

