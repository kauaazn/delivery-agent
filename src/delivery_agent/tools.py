"""The tools the model can call, and the code that runs them.

A tool call crosses three trust boundaries, and each one lives in this file:

1. TOOLS         what the model is told it can do (names, descriptions, JSON schemas).
2. execute_tool  what actually runs. The model's arguments are untrusted input, so they are
                 validated here, in code, before the shop is touched.
3. ToolError     the model-facing failure. Its message is sent back as an `is_error` tool
                 result so the model can explain the problem or try something else.
"""
from __future__ import annotations

import json

from .catalog import TAGS, ZONES
from .shop import MAX_QUANTITY, Shop, ShopError


class ToolError(Exception):
    """A tool call that cannot be completed. The message goes back to the model."""


# --- 1. What the model is told --------------------------------------------------------------


def _object(properties: dict, required: list[str]) -> dict:
    """JSON schema for a tool's arguments. `additionalProperties: False` forbids invented arguments."""
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


_ITEMS = {
    "type": "array",
    "description": "The items of the order. Use item ids returned by search_menu; never guess an id.",
    "minItems": 1,
    "items": _object(
        {
            "item_id": {"type": "integer", "description": "Item id from search_menu"},
            "quantity": {"type": "integer", "minimum": 1, "maximum": MAX_QUANTITY},
        },
        ["item_id", "quantity"],
    ),
}
_ZONE = {"type": "string", "enum": sorted(ZONES), "description": "Delivery zone of the customer"}
_COUPON = {"type": "string", "description": "Optional coupon code, exactly as the customer typed it"}

# The `description` of each tool is an instruction to the model: when to use it, what it returns.
TOOLS: list[dict] = [
    {
        "name": "search_menu",
        "description": (
            "Search the menu by words (a dish, a restaurant or a category such as pizza, bebida, sobremesa). "
            "Optionally filter by maximum price in reais and by dietary tags. Returns up to 8 items with "
            "their ids and prices. Always use it to find items; never guess ids or prices."
        ),
        "input_schema": _object(
            {
                "query": {"type": "string", "description": "Words to look for, e.g. 'pizza calabresa'"},
                "max_price": {"type": "number", "description": "Maximum price per item, in reais"},
                "tags": {"type": "array", "items": {"type": "string", "enum": sorted(TAGS)}},
            },
            ["query"],
        ),
    },
    {
        "name": "quote_order",
        "description": (
            "Price an order without creating it: subtotal, delivery fee, discount and total. "
            "Call it before create_order so the customer sees the exact total."
        ),
        "input_schema": _object({"items": _ITEMS, "zone": _ZONE, "coupon_code": _COUPON}, ["items", "zone"]),
    },
    {
        "name": "create_order",
        "description": (
            "Place the order. This changes data, so the customer must confirm it first. "
            "The order is re-priced by the shop, so never state a price that quote_order did not return."
        ),
        "input_schema": _object(
            {
                "items": _ITEMS,
                "zone": _ZONE,
                "customer_name": {"type": "string", "description": "First name of the customer"},
                "coupon_code": _COUPON,
            },
            ["items", "zone", "customer_name"],
        ),
    },
    {
        "name": "get_order_status",
        "description": "Look up the status and the remaining delivery time of an order by its id, like ORD-1001.",
        "input_schema": _object({"order_id": {"type": "string", "description": "Order id, like ORD-1001"}}, ["order_id"]),
    },
    {
        "name": "cancel_order",
        "description": (
            "Cancel an order by its id. This changes data, so the customer must confirm it first. "
            "It only works while the order is being received or prepared."
        ),
        "input_schema": _object({"order_id": {"type": "string", "description": "Order id, like ORD-1001"}}, ["order_id"]),
    },
]

# Tools that change data. The agent asks a human before running any of them.
WRITE_TOOLS: set[str] = {"create_order", "cancel_order"}


# --- 2. Validating what the model sends -----------------------------------------------------


def _check_keys(args: dict, allowed: set[str], required: set[str]) -> None:
    """Enforce the schema in code: the API does not guarantee that the model respects it."""
    unexpected = sorted(set(args) - allowed)
    if unexpected:
        raise ToolError(f"unexpected argument(s): {', '.join(unexpected)}")
    missing = sorted(required - set(args))
    if missing:
        raise ToolError(f"missing argument(s): {', '.join(missing)}")


def _text(args: dict, key: str, max_len: int) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"'{key}' must be a non-empty string")
    if len(value.strip()) > max_len:
        raise ToolError(f"'{key}' must have at most {max_len} characters")
    return value.strip()


def _int(value: object, label: str) -> int:
    # bool is a subclass of int in Python, so True would otherwise pass as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{label} must be an integer")
    return value


def _items(args: dict) -> list[tuple[int, int]]:
    raw = args.get("items")
    if not isinstance(raw, list) or not raw:
        raise ToolError("'items' must be a non-empty list")
    parsed = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ToolError("each entry of 'items' must be an object with item_id and quantity")
        # No other key is accepted: in particular, the model cannot send a price.
        _check_keys(entry, {"item_id", "quantity"}, {"item_id", "quantity"})
        parsed.append((_int(entry["item_id"], "'item_id'"), _int(entry["quantity"], "'quantity'")))
    return parsed


def _coupon(args: dict) -> str | None:
    value = args.get("coupon_code")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError("'coupon_code' must be a string")
    return value.strip() or None


# --- 3. The tools themselves ----------------------------------------------------------------


def _search_menu(args: dict, shop: Shop) -> dict:
    _check_keys(args, {"query", "max_price", "tags"}, {"query"})
    query = _text(args, "query", 80)
    max_price_cents = None
    if args.get("max_price") is not None:
        price = args["max_price"]
        if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
            raise ToolError("'max_price' must be a positive number of reais")
        max_price_cents = round(price * 100)  # money becomes integer cents at the boundary
    tags = args.get("tags")
    if tags is not None:
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ToolError("'tags' must be a list of strings")
        unknown = sorted(set(tags) - TAGS)
        if unknown:
            raise ToolError(f"unknown tags: {', '.join(unknown)}. Allowed: {', '.join(sorted(TAGS))}")
    results = shop.search(query, max_price_cents=max_price_cents, tags=tags)
    return {"count": len(results), "items": results}


def _quote_order(args: dict, shop: Shop) -> dict:
    _check_keys(args, {"items", "zone", "coupon_code"}, {"items", "zone"})
    return shop.quote(_items(args), _text(args, "zone", 30), _coupon(args))


def _create_order(args: dict, shop: Shop) -> dict:
    _check_keys(args, {"items", "zone", "customer_name", "coupon_code"}, {"items", "zone", "customer_name"})
    return shop.place_order(_items(args), _text(args, "zone", 30), _text(args, "customer_name", 60), _coupon(args))


def _get_order_status(args: dict, shop: Shop) -> dict:
    _check_keys(args, {"order_id"}, {"order_id"})
    return shop.order_status(_text(args, "order_id", 20))


def _cancel_order(args: dict, shop: Shop) -> dict:
    _check_keys(args, {"order_id"}, {"order_id"})
    return shop.cancel_order(_text(args, "order_id", 20))


_HANDLERS = {
    "search_menu": _search_menu,
    "quote_order": _quote_order,
    "create_order": _create_order,
    "get_order_status": _get_order_status,
    "cancel_order": _cancel_order,
}


def execute_tool(name: str, args: dict, shop: Shop) -> str:
    """Run one tool call and return its result as a JSON string."""
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ToolError(f"unknown tool: {name}")
    if not isinstance(args, dict):
        raise ToolError("tool arguments must be a JSON object")
    try:
        result = handler(args, shop)
    except ShopError as exc:
        # Business-rule failures (unknown item, mixed restaurants, late cancel...) reach the model as text.
        raise ToolError(str(exc)) from exc
    return json.dumps(result, ensure_ascii=False)
