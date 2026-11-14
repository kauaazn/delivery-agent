"""The tools: definitions, validation of the model's arguments, and the errors it gets back."""
import json

import pytest

from delivery_agent.catalog import ZONES
from delivery_agent.tools import TOOLS, WRITE_TOOLS, ToolError, execute_tool

ITEMS = [{"item_id": 1, "quantity": 2}]  # 2 x Pizza Margherita
ORDER = {"items": ITEMS, "zone": "centro", "customer_name": "Ana"}


def run(shop, name, args):
    return json.loads(execute_tool(name, args, shop))


# --- definitions ------------------------------------------------------------------------------


def test_tool_definitions_are_well_formed():
    names = [tool["name"] for tool in TOOLS]
    assert len(names) == len(set(names)), "tool names must be unique"
    for tool in TOOLS:
        assert tool["description"].strip(), f"{tool['name']} needs a description the model can act on"
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) <= set(schema["properties"])


def test_the_zone_choices_come_from_the_catalog():
    quote = next(tool for tool in TOOLS if tool["name"] == "quote_order")
    assert quote["input_schema"]["properties"]["zone"]["enum"] == sorted(ZONES)


def test_only_the_tools_that_change_data_need_confirmation():
    assert WRITE_TOOLS == {"create_order", "cancel_order"}


# --- what the tools do ------------------------------------------------------------------------


def test_search_menu_returns_ids_and_prices(shop):
    result = run(shop, "search_menu", {"query": "pizza vegana"})
    first = result["items"][0]
    assert result["count"] >= 1
    assert first["name"] == "Pizza Vegana de Cogumelos" and first["price_brl"] == "R$ 54,00"


def test_search_menu_takes_the_price_in_reais(shop):
    result = run(shop, "search_menu", {"query": "burger", "max_price": 30})
    assert result["items"][0]["name"] == "Cheeseburger Clássico"
    assert all(item["price_cents"] <= 3000 for item in result["items"])


def test_search_menu_filters_by_tags(shop):
    result = run(shop, "search_menu", {"query": "pizza", "tags": ["vegan"]})
    assert [item["name"] for item in result["items"]] == ["Pizza Vegana de Cogumelos"]


def test_quote_order_prices_the_order(shop):
    quote = run(shop, "quote_order", {"items": ITEMS, "zone": "centro"})
    assert quote["total_cents"] == 8900


def test_create_order_places_the_order(shop):
    order = run(shop, "create_order", ORDER)
    assert order["order_id"] == "ORD-1001" and order["total_cents"] == 8900
    assert shop.order_count == 1


def test_status_and_cancel_of_an_order(shop, clock):
    order_id = run(shop, "create_order", ORDER)["order_id"]
    clock.advance(5)
    assert run(shop, "get_order_status", {"order_id": order_id})["status"] == "preparing"
    assert run(shop, "cancel_order", {"order_id": order_id}) == {"cancelled": True, "order_id": order_id}


def test_results_keep_accents(shop):
    assert "Mediterrânea" in execute_tool("search_menu", {"query": "mediterranea"}, shop)


# --- the model's arguments are untrusted ------------------------------------------------------


@pytest.mark.parametrize(
    "name, args",
    [
        ("search_menu", {}),  # missing query
        ("search_menu", {"query": "  "}),
        ("search_menu", {"query": "pizza", "max_price": -5}),
        ("search_menu", {"query": "pizza", "max_price": True}),
        ("search_menu", {"query": "pizza", "tags": ["halal"]}),
        ("search_menu", {"query": "pizza", "tags": "vegan"}),
        ("search_menu", {"query": "pizza", "sort": "price"}),  # an argument that does not exist
        ("quote_order", {"items": [], "zone": "centro"}),
        ("quote_order", {"items": [{"item_id": "1", "quantity": 1}], "zone": "centro"}),
        ("quote_order", {"items": [{"item_id": 1, "quantity": 1.5}], "zone": "centro"}),
        ("quote_order", {"items": [{"item_id": 1, "quantity": 1, "price": 1}], "zone": "centro"}),  # the model cannot set a price
        ("quote_order", {"items": ["pizza"], "zone": "centro"}),
        ("quote_order", {"items": ITEMS, "zone": ""}),
        ("quote_order", {"items": ITEMS, "zone": "centro", "coupon_code": 10}),
        ("create_order", {**ORDER, "customer_name": ""}),
        ("create_order", {**ORDER, "customer_name": "x" * 61}),
        ("create_order", {"items": ITEMS, "zone": "centro"}),  # missing the name
        ("cancel_order", {}),
        ("get_order_status", {"order_id": 1001}),
    ],
)
def test_invalid_arguments_are_rejected_before_the_shop_is_touched(shop, name, args):
    with pytest.raises(ToolError):
        execute_tool(name, args, shop)
    assert shop.order_count == 0


def test_business_rule_failures_become_tool_errors(shop):
    mixed = [{"item_id": 1, "quantity": 1}, {"item_id": 8, "quantity": 1}]  # pizza + temaki
    with pytest.raises(ToolError, match="one restaurant"):
        execute_tool("quote_order", {"items": mixed, "zone": "centro"}, shop)


def test_cancelling_a_late_order_becomes_a_tool_error(shop, clock):
    order_id = run(shop, "create_order", ORDER)["order_id"]
    clock.advance(20)
    with pytest.raises(ToolError, match="can no longer be cancelled"):
        execute_tool("cancel_order", {"order_id": order_id}, shop)


def test_an_unknown_tool_is_a_tool_error(shop):
    with pytest.raises(ToolError, match="unknown tool"):
        execute_tool("drop_database", {}, shop)


def test_arguments_that_are_not_an_object_are_a_tool_error(shop):
    with pytest.raises(ToolError):
        execute_tool("search_menu", "pizza", shop)
