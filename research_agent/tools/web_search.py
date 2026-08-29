"""
Web search tool — wraps Tavily for use by graph nodes.

Provides a thin, reusable layer so callers (opportunity_discovery,
deep_dive_subagent, and any future node) don't each duplicate the
TavilyClient setup, env-var reading, and result-formatting logic.

Public API:
    search(query, max_results=8, search_depth="advanced") -> list[SearchResult]
        Generic Tavily search. Returns a list of SearchResult dataclasses
        with `title`, `url`, and `content` fields.

    search_problems(domain) -> list[SearchResult]
        Convenience wrapper for the discovery node: queries for problems,
        unmet needs, and gaps in `domain`. Default 8 results.

    search_solutions(topic, description="") -> list[SearchResult]
        Convenience wrapper for the deep-dive node: queries for existing
        products / tools that solve `topic`. Default 5 results.

Result shape (SearchResult):
    A small dataclass — nodes that just need strings can call
    `.to_summary()` to get a one-line "Title (url): snippet" string,
    matching the format already used inline in opportunity_discovery.py.

Required env vars:
    TAVILY_API_KEY   (Tavily API key — https://tavily.com)
"""

import os
from dataclasses import dataclass

from tavily import TavilyClient


# Lazy-init so the module can be imported without TAVILY_API_KEY set —
# failures only surface when search() is actually called.
_client: TavilyClient | None = None


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            raise RuntimeError(
                "TAVILY_API_KEY is not set. Add it to .env "
                "(get a key at https://tavily.com)."
            )
        _client = TavilyClient(api_key=api_key)
    return _client


@dataclass(frozen=True)
class SearchResult:
    """One search hit from Tavily, normalized for downstream consumption."""

    title: str
    url: str
    content: str

    def to_summary(self, content_chars: int = 200) -> str:
        """Compact single-line summary: 'Title (url): content[:N]'."""
        snippet = (self.content or "")[:content_chars]
        title = self.title or "Untitled"
        url = self.url or ""
        return f"{title} ({url}): {snippet}"


def _normalize(raw_results: list[dict], content_chars: int = 400) -> list[SearchResult]:
    """Convert Tavily's raw response shape into SearchResult dataclasses.

    The dataclass holds the *full* content; `content_chars` here only
    controls the default snippet length passed to `to_summary()`.
    """
    normalized: list[SearchResult] = []
    for r in raw_results or []:
        normalized.append(
            SearchResult(
                title=r.get("title") or "Untitled",
                url=r.get("url") or "",
                content=r.get("content") or "",
            )
        )
    return normalized


def search(
    query: str,
    max_results: int = 8,
    search_depth: str = "advanced",
) -> list[SearchResult]:
    """
    Generic Tavily search. Returns SearchResult dataclasses.

    Args:
        query: Free-text search query.
        max_results: Cap on results returned (Tavily default 5).
        search_depth: "basic" or "advanced". Default "advanced" for
                      research-grade queries.

    Returns:
        List of SearchResult (empty list if Tavily returns nothing).
    """
    if not query or not query.strip():
        return []

    client = _get_client()
    response = client.search(
        query=query,
        max_results=max_results,
        search_depth=search_depth,
    )
    return _normalize(response.get("results", []))


def search_problems(domain: str, max_results: int = 8) -> list[SearchResult]:
    """
    Convenience: surface problems, unmet needs, and gaps in a domain.
    Used by the opportunity_discovery node.
    """
    query = (
        f"major unsolved problems, unmet needs, gaps, and emerging "
        f"opportunities in the {domain} space"
    )
    return search(query, max_results=max_results, search_depth="advanced")


def search_solutions(
    topic: str,
    description: str = "",
    max_results: int = 5,
) -> list[SearchResult]:
    """
    Convenience: find existing products / tools / solutions for a topic.
    Used by the deep_dive_subagent node.
    """
    parts = [f"existing products, tools, and solutions for {topic}"]
    if description and description.strip():
        parts.append(description.strip())
    query = ". ".join(parts)
    return search(query, max_results=max_results, search_depth="advanced")