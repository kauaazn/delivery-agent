"""Test doubles: a scripted fake of the Claude client. Nothing here touches the network."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from types import SimpleNamespace


@dataclass
class Block:
    """Looks like an SDK content block: .type, .text, .id, .name, .input"""

    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict | None = None


@dataclass
class Response:
    """Looks like an SDK message: .content, .stop_reason, .usage"""

    content: list
    stop_reason: str
    stop_details: object | None = None
    model: str = "fake-model"
    usage: object = field(default_factory=lambda: SimpleNamespace(input_tokens=100, output_tokens=20))


def text(message: str) -> Response:
    """Claude answers and is done."""
    return Response([Block("text", text=message)], "end_turn")


def tool_calls(*calls: tuple[str, dict, str]) -> Response:
    """Claude asks for several tools in one turn. Each call is (name, args, tool_use_id)."""
    blocks = [Block("tool_use", id=tool_id, name=name, input=args) for name, args, tool_id in calls]
    return Response(blocks, "tool_use")


def tool_call(name: str, args: dict, tool_id: str = "toolu_1") -> Response:
    return tool_calls((name, args, tool_id))


def refusal() -> Response:
    return Response([], "refusal", stop_details=SimpleNamespace(category="cyber", explanation="declined"))


class _Endpoint:
    def __init__(self, state: dict, label: str) -> None:
        self._state = state
        self._label = label

    def create(self, **kwargs) -> Response:
        # Snapshot the request: the agent keeps mutating its messages list afterwards.
        self._state["requests"].append({"_endpoint": self._label, **copy.deepcopy(kwargs)})
        if not self._state["script"]:
            raise AssertionError("FakeClaude ran out of scripted responses: Claude was called more times than expected")
        return self._state["script"].pop(0)


class FakeClaude:
    """Stands in for anthropic.Anthropic(). Serves the scripted responses in order.

    Both endpoints (`messages` and `beta.messages`) draw from the same script, and every recorded
    request says which one was used in `_endpoint`.
    """

    def __init__(self, *script: Response) -> None:
        self._state = {"script": list(script), "requests": []}
        self.messages = _Endpoint(self._state, "stable")
        self.beta = SimpleNamespace(messages=_Endpoint(self._state, "beta"))

    @property
    def requests(self) -> list[dict]:
        return self._state["requests"]
