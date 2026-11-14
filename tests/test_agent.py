"""The agent loop, driven by a scripted fake of Claude (no API key, no network)."""
import json

from delivery_agent.agent import Agent
from delivery_agent.tools import TOOLS
from fakes import FakeClaude, refusal, text, tool_call, tool_calls

ORDER = {"items": [{"item_id": 1, "quantity": 2}], "zone": "centro", "customer_name": "Ana"}


def make_agent(fake, shop, confirm=lambda name, args: True, **kwargs):
    return Agent(fake, shop, model="test-model", system="You are a test assistant.", confirm=confirm, **kwargs)


def tool_results(request):
    """The tool_result blocks in the last message sent to Claude, keyed by tool_use_id."""
    last = request["messages"][-1]
    assert last["role"] == "user"
    return {block["tool_use_id"]: block for block in last["content"] if block["type"] == "tool_result"}


# --- the basics -------------------------------------------------------------------------------


def test_answers_without_tools(shop):
    fake = FakeClaude(text("Olá!"))
    assert make_agent(fake, shop).chat("oi") == "Olá!"
    assert len(fake.requests) == 1


def test_the_request_has_the_expected_shape(shop):
    fake = FakeClaude(text("Olá!"))
    make_agent(fake, shop).chat("oi")
    (request,) = fake.requests
    assert request["model"] == "test-model"
    assert request["system"] == "You are a test assistant."
    assert request["tools"] == TOOLS
    assert request["max_tokens"] >= 1024
    assert request["messages"][0] == {"role": "user", "content": "oi"}
    assert "temperature" not in request  # Claude Opus 5.5 rejects sampling parameters


def test_runs_the_requested_tool_and_sends_the_result_back(shop):
    fake = FakeClaude(tool_call("search_menu", {"query": "margherita"}, "toolu_a"), text("Temos a Margherita."))
    assert make_agent(fake, shop).chat("tem margherita?") == "Temos a Margherita."
    assert len(fake.requests) == 2
    results = tool_results(fake.requests[1])
    assert set(results) == {"toolu_a"}
    assert "Pizza Margherita" in results["toolu_a"]["content"]


def test_parallel_tool_calls_are_answered_in_one_user_message(shop):
    fake = FakeClaude(
        tool_calls(("search_menu", {"query": "pizza"}, "toolu_1"), ("search_menu", {"query": "temaki"}, "toolu_2")),
        text("ok"),
    )
    make_agent(fake, shop).chat("mostre pizzas e temakis")
    assert set(tool_results(fake.requests[1])) == {"toolu_1", "toolu_2"}


def test_the_assistant_turn_is_echoed_back_unchanged(shop):
    first = tool_call("search_menu", {"query": "pizza"}, "toolu_a")
    fake = FakeClaude(first, text("ok"))
    make_agent(fake, shop).chat("x")
    assert fake.requests[1]["messages"][1] == {"role": "assistant", "content": first.content}


def test_history_is_kept_between_turns(shop):
    fake = FakeClaude(text("a"), text("b"))
    agent = make_agent(fake, shop)
    agent.chat("um")
    agent.chat("dois")
    assert [m["role"] for m in fake.requests[1]["messages"]] == ["user", "assistant", "user"]


# --- guardrails -------------------------------------------------------------------------------


def test_creating_an_order_needs_confirmation_and_a_no_is_respected(shop):
    asked = []

    def confirm(name, args):
        asked.append((name, args))
        return False

    fake = FakeClaude(tool_call("create_order", ORDER, "toolu_w"), text("Tudo bem, não pedi."))
    answer = make_agent(fake, shop, confirm).chat("pode pedir")
    assert asked == [("create_order", ORDER)]
    assert shop.order_count == 0
    assert tool_results(fake.requests[1])["toolu_w"]["is_error"] is True
    assert answer == "Tudo bem, não pedi."


def test_a_confirmed_order_goes_through(shop):
    fake = FakeClaude(tool_call("create_order", ORDER, "toolu_w"), text("Pedido feito."))
    make_agent(fake, shop, confirm=lambda name, args: True).chat("pode pedir")
    assert shop.order_count == 1
    result = tool_results(fake.requests[1])["toolu_w"]
    assert not result.get("is_error")
    assert json.loads(result["content"])["order_id"] == "ORD-1001"


def test_read_only_tools_never_ask_for_confirmation(shop):
    def confirm(name, args):
        raise AssertionError("read-only tools must not ask the customer")

    fake = FakeClaude(
        tool_calls(
            ("search_menu", {"query": "pizza"}, "toolu_1"),
            ("quote_order", {"items": ORDER["items"], "zone": "centro"}, "toolu_2"),
        ),
        text("ok"),
    )
    make_agent(fake, shop, confirm).chat("x")


def test_tool_errors_go_back_to_the_model_instead_of_crashing(shop):
    bad_item = {"items": [{"item_id": 999, "quantity": 1}], "zone": "centro"}
    fake = FakeClaude(tool_call("quote_order", bad_item, "toolu_q"), text("Esse item não existe."))
    answer = make_agent(fake, shop).chat("quero o item 999")
    result = tool_results(fake.requests[1])["toolu_q"]
    assert result["is_error"] is True and "unknown item" in result["content"]
    assert answer == "Esse item não existe."


def test_an_unknown_tool_is_reported_as_an_error(shop):
    fake = FakeClaude(tool_call("refund_everyone", {}, "toolu_x"), text("Não posso fazer isso."))
    answer = make_agent(fake, shop).chat("devolva tudo")
    assert tool_results(fake.requests[1])["toolu_x"]["is_error"] is True
    assert answer == "Não posso fazer isso."


def test_it_stops_after_max_steps(shop):
    fake = FakeClaude(*[tool_call("search_menu", {"query": "pizza"}, f"toolu_{i}") for i in range(20)])
    answer = make_agent(fake, shop, max_steps=3).chat("x")
    assert len(fake.requests) == 3
    assert isinstance(answer, str) and answer.strip()


def test_a_refusal_is_handled_gracefully(shop):
    answer = make_agent(FakeClaude(refusal()), shop).chat("x")
    assert isinstance(answer, str) and answer.strip()


def test_a_refused_turn_is_not_kept_in_the_history(shop):
    fake = FakeClaude(refusal(), text("ok"))
    agent = make_agent(fake, shop)
    agent.chat("x")
    agent.chat("y")
    assert all(message["role"] == "user" for message in fake.requests[1]["messages"])
