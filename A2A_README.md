# A2A setup (Research + Architect agents, orchestrator)

Two LangGraph-adjacent agents talk to each other over the
[Agent2Agent (A2A) protocol](https://a2a-protocol.org) using the official
[`a2a-sdk`](https://pypi.org/project/a2a-sdk/) (v1.x, protobuf-backed).

## Layout

```
research_agent/a2a_schemas.py    # Opportunity + ResearchResult (mirrors graph/state.py)
research_agent/a2a_agent.py      # bridge: run existing graph headlessly (ai mode)
research_agent/a2a_executor.py   # AgentExecutor adapter (TextPart/DataPart in, DataPart out)
research_agent/a2a_server.py     # A2A server on :8001 (Agent Card + JSON-RPC)
architect_agent/
  schemas.py                     # DesignRequest + SolutionDesign (per buildPlan Phase 2)
  agent.py                       # one OpenRouter LLM call, strict-JSON output
  executor.py                    # AgentExecutor adapter with input validation
  server.py                      # A2A server on :8002
orchestrator/
  agents.yaml                  # MCP-style registry: key -> {url, enabled} (add agents here, no code change)
  registry.py                  # loads agents.yaml + fetches/caches Agent Cards (discovery)
  planner.py                   # LLM router (muse-spark-1.3-contributor via OpenRouter); picks ONE next delegation or finish
  executor.py                  # one delegation: Text/DataPart build, contextId reuse, GetTask polling, input-required handling
  a2a_client.py                # plain HTTP + JSON-RPC helpers (SendMessage/GetTask/CancelTask, artifacts)
  run.py                       # CLI: plan -> delegate -> loop until done -> runs/<ts>/result.json
```

## Run locally

```bash
# 1. API keys (same providers the graph already uses)
cp .env.example .env   # then fill in TAVILY_API_KEY, OPENROUTER_API_KEY, AWS_BEARER_TOKEN_BEDROCK

# 2. Install (python3.11; the repo's graph code targets 3.11/3.12)
pip install -r research_agent/requirements.txt
# NOTE: a2a-sdk 1.x needs protobuf>=6 (pure-Python `protobuf<6` breaks the
# SDK's FastAPI OpenAPI schema generation with
# `FieldDescriptor has no attribute 'is_repeated'`).

# 3. Start both agents (two terminals)
python3.11 -m research_agent.a2a_server --port 8001
python3.11 -m architect_agent.server --port 8002

# 4. Check discovery
curl localhost:8001/.well-known/agent-card.json
curl localhost:8002/.well-known/agent-card.json

# 5. Run the dynamic orchestrator (planner delegates via Agent Cards)
python3.11 -m orchestrator.run --domain "fintech"
# flags: --agents <path.yaml> --max-steps 10 --auto (no input() pauses)
#        --planner-model <openrouter id> (default ORCHESTRATOR_MODEL or meta/muse-spark-1.3-contributor)
#        --research-url / --architect-url override agents.yaml entries
```

Planner needs an OpenRouter key (`OPENROUTER_API_KEY`); the default
planner model may require age attestation on your OpenRouter account —
override with `--planner-model` or `ORCHESTRATOR_MODEL` if so.

Without API keys the servers still start and serve Agent Cards, but any
real research/design call returns a `TASK_STATE_FAILED` task with the
missing-key message instead of hanging — that is the intended Phase 4
behavior, and `runs/<timestamp>/result.json` is only written on a fully
successful end-to-end run.
