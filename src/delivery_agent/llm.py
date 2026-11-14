"""The only module that builds Claude API requests.

Opus 5.5 notes (see the Claude API docs):
  * thinking is always on, so `thinking` is omitted; depth is controlled by effort
  * `temperature`/`top_p`/`top_k` are rejected, and forced `tool_choice` is rejected
  * the server-side refusal fallback (beta) re-runs a declined request on another model
"""
from __future__ import annotations

from typing import Any

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def call_claude(
    client: Any,
    *,
    model: str,
    system: str,
    tools: list[dict],
    messages: list[dict],
    max_tokens: int = 16000,
    fallbacks: bool = False,
):
    """One request to Claude. Returns the SDK response (`.content`, `.stop_reason`, `.usage`)."""
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "tools": tools,
        "messages": messages,
        "output_config": {"effort": "medium"},
    }
    # Claude Haiku 5.5 has no server-side fallback, so never send it there.
    if fallbacks and "haiku" not in model:
        return client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
    return client.messages.create(**params)
