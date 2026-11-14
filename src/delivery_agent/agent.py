"""The agent loop: let Claude call tools until it has an answer.

One user message can take several round trips to Claude:

    user text -> Claude asks for tools -> we run them -> results go back -> Claude answers

The loop below is that cycle, plus four guardrails: a step limit, human confirmation for tools
that change data, tool failures returned as results instead of exceptions, and explicit
handling of refusals.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .llm import call_claude
from .shop import Shop
from .tools import TOOLS, WRITE_TOOLS, ToolError, execute_tool

REFUSAL_MESSAGE = "Não posso ajudar com esse pedido."
STEP_LIMIT_MESSAGE = "Parei porque isso exigiu passos demais. Tente um pedido mais simples."
NO_TEXT_MESSAGE = "(o modelo não enviou nenhuma resposta em texto)"


class Agent:
    def __init__(
        self,
        client: Any,
        shop: Shop,
        *,
        model: str,
        system: str,
        confirm: Callable[[str, dict], bool],
        max_steps: int = 8,
        fallbacks: bool = False,
    ) -> None:
        self.client = client  # anthropic.Anthropic() in production, a scripted fake in tests
        self.shop = shop
        self.model = model
        self.system = system
        self.confirm = confirm  # asked before any tool that changes data
        self.max_steps = max_steps
        self.fallbacks = fallbacks
        self.messages: list[dict] = []  # the whole conversation, kept between turns

    def chat(self, user_text: str) -> str:
        """Handle one user message and return the assistant's final text."""
        self.messages.append({"role": "user", "content": user_text})

        # Guardrail: a bounded loop. A confused model cannot spin forever (or burn money).
        for _ in range(self.max_steps):
            response = call_claude(
                self.client,
                model=self.model,
                system=self.system,
                tools=TOOLS,
                messages=self.messages,
                fallbacks=self.fallbacks,
            )

            # Always read stop_reason before the content.
            if response.stop_reason == "refusal":
                # Not added to the history: a refused turn can be empty and would break the next call.
                return REFUSAL_MESSAGE

            # Echo the assistant turn back exactly as received, thinking blocks included.
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                return _text_of(response) or NO_TEXT_MESSAGE  # "end_turn": Claude is done

            # Claude may ask for several tools in one turn. Every result goes back together,
            # in ONE user message, each tagged with the id of the tool_use it answers.
            results = [self._run_tool(block) for block in response.content if block.type == "tool_use"]
            self.messages.append({"role": "user", "content": results})

        return STEP_LIMIT_MESSAGE

    def _run_tool(self, block: Any) -> dict:
        """Run one tool_use block and build its tool_result. Tool problems never raise."""
        result: dict = {"type": "tool_result", "tool_use_id": block.id}
        try:
            # Guardrail: enforced in code, not only in the prompt. A prompt can be argued with.
            if block.name in WRITE_TOOLS and not self.confirm(block.name, block.input):
                raise ToolError("The customer declined this action. Do not retry it; ask what they want instead.")
            result["content"] = execute_tool(block.name, block.input, self.shop)
        except ToolError as exc:
            # The failure goes back to the model as data, so it can explain it or try something else.
            result["content"] = str(exc)
            result["is_error"] = True
        return result


def _text_of(response: Any) -> str:
    """Join the text blocks of a response (thinking and tool_use blocks are skipped)."""
    return "".join(block.text for block in response.content if block.type == "text")
