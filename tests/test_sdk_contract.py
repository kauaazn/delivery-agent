"""The agent against the REAL Anthropic SDK, with the network replaced by a mock.

This cannot prove that the API accepts a request. It proves what the SDK would send, and that the
SDK's own response objects work with the agent loop, including echoing them back on the next call.
"""
import json

import pytest

httpx2 = pytest.importorskip("httpx2")
anthropic = pytest.importorskip("anthropic")

from delivery_agent.agent import Agent  # noqa: E402
from delivery_agent.llm import FALLBACK_BETA  # noqa: E402
from delivery_agent.shop import Shop  # noqa: E402
from delivery_agent.tools import TOOLS  # noqa: E402
from evals.run import run_scenario  # noqa: E402

ORDER = {"items": [{"item_id": 1, "quantity": 2}], "zone": "centro", "customer_name": "Ana"}


def message(content: list, stop_reason: str) -> dict:
    """A response body, shaped like the Messages API's."""
    return {
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 30},
    }


def tool_use(tool_id: str, name: str, args: dict) -> dict:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": args}


def say(words: str) -> dict:
    return message([{"type": "text", "text": words}], "end_turn")


class MockApi:
    """Serves scripted responses over a mocked network and records every request."""

    def __init__(self, *script: dict) -> None:
        self.script = list(script)
        self.requests: list[dict] = []

    def _handle(self, request: "httpx2.Request") -> "httpx2.Response":
        self.requests.append({"url": request.url, "headers": dict(request.headers), "body": json.loads(request.content)})
        return httpx2.Response(200, json=self.script.pop(0))

    def client(self) -> "anthropic.Anthropic":
        transport = httpx2.MockTransport(self._handle)
        return anthropic.Anthropic(api_key="sk-ant-test", http_client=anthropic.DefaultHttpxClient(transport=transport))


def make_agent(api: MockApi, shop: Shop, confirm=lambda name, args: True, **kwargs) -> Agent:
    return Agent(api.client(), shop, model="claude-opus-5-5", system="You are a test assistant.", confirm=confirm, **kwargs)


def test_a_conversation_works_with_the_real_sdk_objects(shop):
    api = MockApi(
        message([tool_use("toolu_01", "search_menu", {"query": "pizza vegana", "tags": ["vegan"]})], "tool_use"),
        say("Temos a Pizza Vegana de Cogumelos."),
    )
    assert make_agent(api, shop).chat("Quero uma pizza vegana") == "Temos a Pizza Vegana de Cogumelos."
    assert len(api.requests) == 2

    _, assistant_turn, tool_result_turn = api.requests[1]["body"]["messages"]
    assert assistant_turn["role"] == "assistant"
    assert assistant_turn["content"] == [
        {"type": "tool_use", "id": "toolu_01", "name": "search_menu", "input": {"query": "pizza vegana", "tags": ["vegan"]}}
    ]
    (result,) = tool_result_turn["content"]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_01"
    assert "Pizza Vegana de Cogumelos" in result["content"]


def test_the_stable_request_has_the_expected_headers_and_body(shop):
    api = MockApi(say("oi"))
    make_agent(api, shop).chat("oi")
    (request,) = api.requests
    assert request["url"].path == "/v1/messages"
    assert request["headers"]["authorization"] == "Bearer sk-ant-test"  # how SDK 2.x sends the key
    assert "anthropic-version" in request["headers"]
    assert "anthropic-beta" not in request["headers"]
    body = request["body"]
    assert set(body) == {"max_tokens", "messages", "model", "output_config", "system", "tools"}
    assert body["model"] == "claude-opus-5-5"
    assert body["output_config"] == {"effort": "medium"}
    assert [tool["name"] for tool in body["tools"]] == [tool["name"] for tool in TOOLS]


def test_the_fallback_request_carries_the_beta_header_and_parameter(shop):
    api = MockApi(say("oi"))
    make_agent(api, shop, fallbacks=True).chat("oi")
    (request,) = api.requests
    assert FALLBACK_BETA in request["headers"]["anthropic-beta"]
    assert request["body"]["fallbacks"] == "default"


def test_parallel_tool_calls_come_back_in_one_message(shop):
    api = MockApi(
        message([tool_use("toolu_a", "search_menu", {"query": "pizza"}), tool_use("toolu_b", "search_menu", {"query": "temaki"})], "tool_use"),
        say("ok"),
    )
    make_agent(api, shop).chat("pizzas e temakis")
    last = api.requests[1]["body"]["messages"][-1]
    assert [block["tool_use_id"] for block in last["content"]] == ["toolu_a", "toolu_b"]


def test_a_declined_order_travels_back_as_an_error(shop):
    api = MockApi(message([tool_use("toolu_w", "create_order", ORDER)], "tool_use"), say("Tudo bem."))
    make_agent(api, shop, confirm=lambda name, args: False).chat("pode pedir")
    (result,) = api.requests[1]["body"]["messages"][-1]["content"]
    assert result["is_error"] is True and shop.order_count == 0


def test_a_confirmed_order_is_placed_through_the_real_sdk(shop):
    api = MockApi(message([tool_use("toolu_w", "create_order", ORDER)], "tool_use"), say("Pedido feito."))
    make_agent(api, shop).chat("pode pedir")
    assert shop.order_count == 1


def test_tokens_are_counted_from_real_responses(shop):
    api = MockApi(message([tool_use("toolu_01", "search_menu", {"query": "pizza"})], "tool_use"), say("ok"))
    result = run_scenario({"id": "t", "user": ["x"]}, api.client(), model="claude-opus-5-5")
    assert (result["calls"], result["input_tokens"], result["output_tokens"]) == (2, 240, 60)
