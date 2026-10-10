"""A2A server entrypoint for the Architect Agent.

Run with:
    python3.11 -m architect_agent.server --port 8002

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

from architect_agent.executor import ArchitectAgentExecutor

DEFAULT_PORT = 8002


def build_agent_card(url: str) -> AgentCard:
    return AgentCard(
        name="Architect Agent",
        description="Designs a solution architecture for a given problem statement",
        version="0.1.0",
        default_input_modes=["application/json", "text/plain"],
        default_output_modes=["application/json"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(
                url=url, protocol_binding="JSONRPC", protocol_version="1.0"
            )
        ],
        skills=[
            AgentSkill(
                id="design_solution",
                name="Design Solution",
                description="Given a problem statement and research context, proposes an architecture and build approach",
                tags=["architecture", "design"],
            )
        ],
    )


def build_app(public_url: str) -> FastAPI:
    card = build_agent_card(public_url)
    handler = DefaultRequestHandler(
        agent_executor=ArchitectAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    app = FastAPI(title="Architect Agent (A2A)")
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/"),
        rest_routes=create_rest_routes(handler),
    )
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Architect Agent A2A server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    public_url = f"http://{args.host}:{args.port}"
    uvicorn.run(build_app(public_url), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
