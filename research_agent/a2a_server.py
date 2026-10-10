"""A2A server entrypoint for the Research Agent.

Run with:
    python3.11 -m research_agent.a2a_server --port 8001

Exposes:
    GET  /.well-known/agent-card.json   Agent Card (discovery)
    POST /                              JSON-RPC message/send
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from fastapi import FastAPI

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
    create_rest_routes,
)
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

from research_agent.a2a_executor import ResearchAgentExecutor

DEFAULT_PORT = 8001


def build_agent_card(url: str) -> AgentCard:
    return AgentCard(
        name="Research Agent",
        description="Extracts and evaluates business opportunities/problem statements for a given domain",
        version="0.1.0",
        default_input_modes=["text/plain", "application/json"],
        default_output_modes=["application/json"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(
                url=url, protocol_binding="JSONRPC", protocol_version="1.0"
            )
        ],
        skills=[
            AgentSkill(
                id="research_opportunities",
                name="Research Opportunities",
                description="Given a domain or problem statement, returns candidate opportunities tagged worth-solving or saturated",
                tags=["research"],
            )
        ],
    )


def build_app(public_url: str) -> FastAPI:
    card = build_agent_card(public_url)
    handler = DefaultRequestHandler(
        agent_executor=ResearchAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    app = FastAPI(title="Research Agent (A2A)")
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/"),
        rest_routes=create_rest_routes(handler),
    )
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Research Agent A2A server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    public_url = f"http://{args.host}:{args.port}"
    uvicorn.run(build_app(public_url), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
