"""The eval runner itself, tested offline. What the model does is measured by `python -m evals.run`."""
import pytest

from delivery_agent.shop import Shop
from delivery_agent.tools import TOOLS
from evals.run import (
    EXPECTATION_KEYS, _matches, build_shop, check, estimate_cost, load_scenarios, run_scenario, run_scenario_safely,
    tool_calls_from,
)
from fakes import FakeClaude, text, tool_call, tool_calls

TOOL_NAMES = {tool["name"] for tool in TOOLS}


# --- the scenario file is data worth checking -------------------------------------------------


def test_scenario_ids_are_unique():
    ids = [scenario["id"] for scenario in load_scenarios()]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("scenario", load_scenarios(), ids=lambda s: s["id"])
def test_every_scenario_is_well_formed(scenario):
    assert scenario["user"] and all(isinstance(m, str) and m.strip() for m in scenario["user"])
    expect = scenario.get("expect", {})
    assert set(expect) <= EXPECTATION_KEYS
    mentioned = set(expect.get("tools_called", [])) | set(expect.get("tools_not_called", [])) | set(expect.get("args_contain", {}))
    assert mentioned <= TOOL_NAMES, f"unknown tool in {scenario['id']}"
    build_shop(scenario.get("setup"))  # the starting orders must be valid


# --- matching ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expected, actual, result",
    [
        (30, 30.0, True),
        (30, 31, False),
        (30, True, False),
        ("Centro", " centro ", True),
        (["vegan"], ["vegan", "gluten_free"], True),
        (["vegan", "spicy"], ["vegan"], False),
        (["vegan"], "vegan", False),
        ([{"item_id": 1, "quantity": 2}], [{"quantity": 2, "item_id": 1}], True),  # key order does not matter
        ([{"item_id": 1, "quantity": 2}], [{"item_id": 1, "quantity": 3}], False),
    ],
)
def test_matching_rules(expected, actual, result):
    assert _matches(expected, actual) is result


# --- checking ---------------------------------------------------------------------------------


def test_check_passes_when_everything_is_met():
    calls = [("search_menu", {"query": "pizza", "tags": ["vegan"]})]
    expect = {"tools_called": ["search_menu"], "args_contain": {"search_menu": {"tags": ["vegan"]}}, "orders_total": 0}
    assert check(expect, calls, Shop()) == []


def test_check_reports_each_kind_of_failure():
    shop = Shop()
    shop.place_order([(1, 1)], "centro", "Ana")
    expect = {
        "tools_called": ["quote_order"],
        "tools_not_called": ["create_order"],
        "args_contain": {"search_menu": {"tags": ["vegan"]}},
        "orders_total": 0,
        "order_status": {"ORD-1001": "cancelled"},
    }
    calls = [("create_order", {}), ("search_menu", {"query": "pizza"})]
    failures = check(expect, calls, shop)
    assert len(failures) == 5
    assert any("expected a call to quote_order" in f for f in failures)
    assert any("create_order should not have been called" in f for f in failures)


# --- running a scenario with a scripted model -------------------------------------------------


VEGAN = {
    "id": "vegan",
    "user": ["Quero uma pizza vegana"],
    "expect": {"tools_called": ["search_menu"], "args_contain": {"search_menu": {"tags": ["vegan"]}}},
}


def test_a_scenario_passes_when_the_model_does_the_right_thing():
    fake = FakeClaude(tool_call("search_menu", {"query": "pizza", "tags": ["vegan"]}), text("Temos a pizza vegana."))
    result = run_scenario(VEGAN, fake)
    assert result["passed"] and result["tools"] == ["search_menu"]


def test_a_scenario_fails_when_the_model_skips_the_tool():
    result = run_scenario(VEGAN, FakeClaude(text("Claro, qual sabor?")))
    assert not result["passed"]
    assert "expected a call to search_menu" in result["failures"][0]


def test_the_scenario_decides_whether_the_customer_confirms():
    order = {"items": [{"item_id": 1, "quantity": 1}], "zone": "centro", "customer_name": "Ana"}
    scenario = {"id": "no", "user": ["pede"], "confirm": False, "expect": {"orders_total": 0}}
    result = run_scenario(scenario, FakeClaude(tool_call("create_order", order), text("ok")))
    assert result["passed"] and result["confirmations_asked"] == ["create_order"]


def test_a_crash_is_reported_as_a_failed_scenario_not_as_the_end_of_the_run():
    result = run_scenario_safely({"id": "boom", "user": ["x"]}, FakeClaude())  # no scripted answer: the fake raises
    assert result["passed"] is False
    assert result["failures"][0].startswith("crashed: AssertionError")


def test_tokens_are_added_up_across_calls():
    fake = FakeClaude(tool_call("search_menu", {"query": "pizza"}), text("ok"))  # each fake call: 100 in, 20 out
    result = run_scenario({"id": "t", "user": ["x"]}, fake)
    assert (result["calls"], result["input_tokens"], result["output_tokens"]) == (2, 200, 40)


def test_tool_calls_are_read_in_order_from_the_conversation():
    fake = FakeClaude(
        tool_calls(("search_menu", {"query": "pizza"}, "t1"), ("search_menu", {"query": "temaki"}, "t2")),
        tool_call("quote_order", {"items": [{"item_id": 1, "quantity": 1}], "zone": "centro"}, "t3"),
        text("ok"),
    )
    from delivery_agent.agent import Agent

    agent = Agent(fake, Shop(), model="m", system="s", confirm=lambda n, a: True)
    agent.chat("x")
    assert [name for name, _ in tool_calls_from(agent.messages)] == ["search_menu", "search_menu", "quote_order"]


def test_the_starting_orders_and_time_of_a_scenario_are_applied():
    shop = build_shop({"orders": [{"items": [[1, 1]], "zone": "centro", "customer_name": "Ana"}], "advance_minutes": 5})
    assert shop.order_status("ORD-1001")["status"] == "preparing"


# --- cost -------------------------------------------------------------------------------------


def test_cost_estimate_uses_the_price_table():
    assert estimate_cost("claude-opus-5-5", 1_000_000, 1_000_000) == pytest.approx(24.0)
    assert estimate_cost("claude-haiku-5-5", 1_000_000, 0) == pytest.approx(0.10)
    assert estimate_cost("some-future-model", 10, 10) is None
