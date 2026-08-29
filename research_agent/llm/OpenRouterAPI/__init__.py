"""
OpenRouter LLM factory.

Returns a configured OpenRouter LLM client. The API key and model ID are
read from environment variables, which are auto-loaded from `.env` at
import time.

Usage:
    from llm.OpenRouterAPI import get_openrouter_llm

    llm = get_openrouter_llm(
        model_name="anthropic/claude-sonnet-4-5",
        temperature=0.2,
        max_tokens=1024,
    )
    text = llm.invoke(messages)

Env vars (loaded from .env at import):
    OPENROUTER_API_KEY    (required)
    OPENROUTER_MODEL      (optional; fallback if model_name omitted)
    OPENROUTER_BASE_URL   (optional, default https://openrouter.ai/api/v1)
    OPENROUTER_SITE_URL   (optional, ranking metadata)
    OPENROUTER_APP_NAME   (optional, ranking metadata)
"""

from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv

# Resolve the project root dynamically. From
# research_agent/llm/OpenRouterAPI/__init__.py, .env is 3 parents up.
# Using .resolve() handles symlinks; parents[3] is the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")

import os

from openai import OpenAI


class OpenRouterLLM:
    """Minimal OpenRouter (OpenAI-compatible) client wrapper."""

    def __init__(
        self,
        model: str | None = None,
        **defaults,
    ):
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set in the environment."
            )

        self.model = model or os.environ.get("OPENROUTER_MODEL")
        if not self.model:
            raise RuntimeError(
                "model_name not provided and OPENROUTER_MODEL is not set."
            )

        self.client = OpenAI(
            api_key=api_key,
            base_url=os.environ.get(
                "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
            ),
            default_headers={
                "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL", ""),
                "X-Title": os.environ.get("OPENROUTER_APP_NAME", ""),
            },
        )
        self.defaults = defaults

    def invoke(self, messages: list[dict], **overrides) -> str:
        kwargs = {**self.defaults, **overrides}
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            **kwargs,
        )
        return response.choices[0].message.content

    def stream(self, messages: list[dict], **overrides) -> Iterator[str]:
        kwargs = {**self.defaults, **overrides}
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            **kwargs,
        )
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content


def get_openrouter_llm(
    model_name: str | None = None,
    temperature: float | None = None,
    **kwargs,
) -> OpenRouterLLM:
    """
    Build a configured OpenRouter LLM client.

    Args:
        model_name: OpenRouter model ID (e.g. "anthropic/claude-sonnet-4-5").
                    Falls back to the OPENROUTER_MODEL env var.
        temperature: Sampling temperature. Optional.
        **kwargs: Other chat.completions params (e.g. max_tokens, top_p).

    Returns:
        An OpenRouterLLM instance with invoke() / stream() methods.

    Raises:
        RuntimeError: If API key is missing or model is unset.
    """
    defaults: dict = {}
    if temperature is not None:
        defaults["temperature"] = temperature

    return OpenRouterLLM(
        model=model_name,
        **defaults,
        **kwargs,
    )
