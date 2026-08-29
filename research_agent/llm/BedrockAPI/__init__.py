"""
Bedrock Mantle LLM factory.

Bedrock Mantle is AWS Bedrock's OpenAI-compatible inference endpoint
(separate from the standard bedrock-runtime Converse API). It hosts
models like `openai.gpt-oss-120b` that don't support the Converse API.

This module exposes a thin `BedrockLLM` wrapper that's API-compatible
with the previous Converse-based version: `get_bedrock_llm(...)` and
`invoke(messages, system=...)`. Under the hood it talks to the Mantle
endpoint via the `openai` Python SDK pointed at
`https://bedrock-mantle.{region}.api.aws/v1`.

Why Mantle instead of Converse:
    GPT-OSS models on Bedrock are only exposed via the Mantle
    OpenAI-compatible endpoint. The Converse API returns 404 for these
    model IDs.

Usage:
    from llm.BedrockAPI import get_bedrock_llm

    llm = get_bedrock_llm(
        model_name="openai.gpt-oss-120b",
        temperature=0.3,
        max_tokens=2048,
    )
    text = llm.invoke(messages, system="You are concise.")

Env vars (loaded from .env at import):
    AWS_BEARER_TOKEN_BEDROCK   (required) — Bedrock/Mantle API key
    BEDROCK_MANTLE_REGION      (optional, default eu-west-1)
    BEDROCK_MODEL_ID           (optional; fallback if model_name omitted)
"""

from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv

# Resolve the project root dynamically. From
# research_agent/llm/BedrockAPI/__init__.py, .env is 3 parents up.
# Using .resolve() handles symlinks; parents[3] is the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")

import os

from openai import OpenAI


class BedrockLLM:
    """Minimal Mantle (OpenAI-compatible) client wrapper."""

    def __init__(
        self,
        model: str | None = None,
        region: str | None = None,
        endpoint_url: str | None = None,
        **defaults,
    ):
        api_key = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
        if not api_key:
            raise RuntimeError(
                "AWS_BEARER_TOKEN_BEDROCK is not set in the environment."
            )

        self.model = model or os.environ.get("BEDROCK_MODEL_ID")
        if not self.model:
            raise RuntimeError(
                "model_name not provided and BEDROCK_MODEL_ID is not set."
            )

        # Resolve the Mantle base URL. Override via endpoint_url, or
        # build from BEDROCK_MANTLE_REGION / AWS_REGION.
        if endpoint_url:
            base_url = endpoint_url
        else:
            region = region or os.environ.get("BEDROCK_MANTLE_REGION") \
                or os.environ.get("AWS_REGION") \
                or "eu-west-1"
            base_url = f"https://bedrock-mantle.{region}.api.aws/v1"

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.defaults = defaults

    def invoke(
        self,
        messages: list[dict],
        system: str | None = None,
        **overrides,
    ) -> str:
        # Bedrock Mantle /chat/completions takes system as a message with
        # role=system, not as a separate top-level field (that's a Claude /
        # Converse API thing).
        full_messages = list(messages)
        if system:
            # If the caller already provided a system message, replace it;
            # otherwise prepend. Avoids duplicate-system surprises.
            if full_messages and full_messages[0].get("role") == "system":
                full_messages[0] = {"role": "system", "content": system}
            else:
                full_messages = [{"role": "system", "content": system}] + full_messages

        kwargs = {**self.defaults, **overrides}
        # Strip None values so we don't accidentally pass temperature=None
        # and trip OpenAI SDK validation.
        kwargs = {k: v for k, v in kwargs.items() if v is not None}

        response = self.client.chat.completions.create(
            model=self.model,
            messages=full_messages,
            **kwargs,
        )
        return response.choices[0].message.content

    def stream(
        self,
        messages: list[dict],
        system: str | None = None,
        **overrides,
    ):
        full_messages = list(messages)
        if system:
            if full_messages and full_messages[0].get("role") == "system":
                full_messages[0] = {"role": "system", "content": system}
            else:
                full_messages = [{"role": "system", "content": system}] + full_messages

        kwargs = {**self.defaults, **overrides}
        kwargs = {k: v for k, v in kwargs.items() if v is not None}

        response = self.client.chat.completions.create(
            model=self.model,
            messages=full_messages,
            stream=True,
            **kwargs,
        )
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content


def get_bedrock_llm(
    model_name: str | None = None,
    temperature: float | None = None,
    **kwargs,
) -> BedrockLLM:
    """
    Build a configured Mantle LLM client.

    Args:
        model_name: Mantle model ID (e.g. "openai.gpt-oss-120b").
                    Falls back to the BEDROCK_MODEL_ID env var.
        temperature: Sampling temperature. Optional.
        **kwargs: Other chat.completions params (e.g. max_tokens, top_p).

    Returns:
        A BedrockLLM instance with invoke() / stream() methods.

    Raises:
        RuntimeError: If API key is missing or model is unset.
    """
    defaults: dict = {}
    if temperature is not None:
        defaults["temperature"] = temperature

    return BedrockLLM(
        model=model_name,
        **defaults,
        **kwargs,
    )