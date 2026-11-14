"""The business logic of the fictional delivery shop. No AI and no HTTP: plain, testable Python.

Rules worth knowing:
- money is integer cents, never floats
- the model never sets a price: every total is computed here, from the catalog
- an order contains items from ONE restaurant
- an order can only be cancelled while it is being received or prepared
- time is injected (`clock`), so order statuses can be tested without waiting
"""
from __future__ import annotations

import math
import time
import unicodedata
from collections.abc import Callable

from .catalog import COUPONS, MENU, ZONES

MAX_LINES = 10
MAX_QUANTITY = 10
CANCELLABLE = {"received", "preparing"}
RECEIVED_UNTIL = 2  # minutes after the order
PREPARING_UNTIL = 15  # minutes after the order; after that the order is on the way until its ETA
STOPWORDS = {"com", "uma", "uns", "para", "pra", "que", "tem", "quero", "por", "favor", "the", "and"}


class ShopError(Exception):
    """A business-rule violation. The message is safe to show to the model."""


def brl(cents: int) -> str:
    """Format integer cents as Brazilian reais: 5490 -> 'R$ 54,90'."""
    reais, rest = divmod(cents, 100)
    return "R$ " + f"{reais:,}".replace(",", ".") + f",{rest:02d}"


def normalize(text: str) -> str:
    """Lowercase and strip accents, so 'Calabresa' matches 'calabresa' and 'Mediterrânea' matches 'mediterranea'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower().strip()


def _public(item: dict) -> dict:
    return {
        "id": item["id"], "restaurant": item["restaurant"], "name": item["name"],
        "description": item["description"], "price_cents": item["price_cents"],
        "price_brl": brl(item["price_cents"]), "tags": list(item["tags"]),
    }


_FIELD_WEIGHTS = (("name", 3), ("category", 2), ("restaurant", 1), ("description", 1), ("tags", 1))


def _score(words: list[str], item: dict) -> int:
    """How well an item matches the words: a hit in the name counts more than one in the description."""
    fields = {
        "name": normalize(item["name"]), "category": normalize(item["category"]),
        "restaurant": normalize(item["restaurant"]), "description": normalize(item["description"]),
        "tags": normalize(" ".join(item["tags"])),
    }
    return sum(weight for word in words for name, weight in _FIELD_WEIGHTS if word in fields[name])


class Shop:
    def __init__(
        self,
        menu: list[dict] | None = None,
        zones: dict[str, dict] | None = None,
        coupons: dict[str, dict] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._menu = {item["id"]: item for item in (MENU if menu is None else menu)}
        self._zones = dict(ZONES if zones is None else zones)
        self._coupons = dict(COUPONS if coupons is None else coupons)
        self._clock = clock
        self._orders: dict[str, dict] = {}
        self._next_id = 1001

    @property
    def order_count(self) -> int:
        return len(self._orders)

    # --- reading the menu ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        max_price_cents: int | None = None,
        tags: list[str] | None = None,
        limit: int = 8,
    ) -> list[dict]:
        """Items matching the query words, cheapest first among equal matches."""
        words = [w for w in normalize(query).split() if len(w) >= 3 and w not in STOPWORDS]
        if not words:
            raise ShopError("the search query needs at least one meaningful word")
        wanted = set(tags or [])
        found = []
        for item in self._menu.values():
            if max_price_cents is not None and item["price_cents"] > max_price_cents:
                continue
            if not wanted <= set(item["tags"]):
                continue
            score = _score(words, item)
            if score:
                found.append((score, item))
        found.sort(key=lambda pair: (-pair[0], pair[1]["price_cents"], pair[1]["id"]))
        return [_public(item) for _, item in found[:limit]]

    # --- pricing ---------------------------------------------------------------------------

    def quote(self, items: list[tuple[int, int]], zone: str, coupon_code: str | None = None) -> dict:
        """Price an order without creating it. `items` is a list of (item_id, quantity)."""
        lines = self._lines(items)
        restaurants = sorted({line["restaurant"] for line in lines})
        if len(restaurants) > 1:
            raise ShopError("an order can only have items from one restaurant, but this one mixes: " + ", ".join(restaurants))
        zone_name, zone_info = self._zone(zone)

        subtotal = sum(line["line_cents"] for line in lines)
        fee, discount, applied = zone_info["fee_cents"], 0, None
        if coupon_code:
            applied = coupon_code.strip().upper()
            coupon = self._coupons.get(applied)
            if coupon is None:
                raise ShopError(f"unknown coupon: {applied}")
            if subtotal < coupon["min_subtotal_cents"]:
                raise ShopError(f"coupon {applied} needs a subtotal of at least {brl(coupon['min_subtotal_cents'])}")
            if coupon["kind"] == "percent":
                discount = subtotal * coupon["value"] // 100
            elif coupon["kind"] == "free_delivery":
                fee = 0
        total = subtotal + fee - discount
        return {
            "restaurant": restaurants[0],
            "zone": zone_name,
            "lines": [
                {
                    "item_id": line["item_id"], "name": line["name"], "quantity": line["quantity"],
                    "unit_brl": brl(line["unit_cents"]), "line_brl": brl(line["line_cents"]),
                }
                for line in lines
            ],
            "subtotal_cents": subtotal, "delivery_fee_cents": fee, "discount_cents": discount, "total_cents": total,
            "subtotal_brl": brl(subtotal), "delivery_fee_brl": brl(fee), "discount_brl": brl(discount),
            "total_brl": brl(total),
            "coupon": applied,
            "eta_minutes": zone_info["eta_minutes"],
        }

    # --- orders ----------------------------------------------------------------------------

    def place_order(
        self,
        items: list[tuple[int, int]],
        zone: str,
        customer_name: str,
        coupon_code: str | None = None,
    ) -> dict:
        name = (customer_name or "").strip()
        if not name:
            raise ShopError("the customer name must not be empty")
        # Re-priced here on purpose: nothing the model said about prices is ever trusted.
        quote = self.quote(items, zone, coupon_code)
        order_id = f"ORD-{self._next_id}"
        self._next_id += 1
        self._orders[order_id] = {**quote, "order_id": order_id, "customer_name": name,
                                  "created_at": self._clock(), "cancelled": False}
        return {
            "order_id": order_id, "status": "received", "restaurant": quote["restaurant"],
            "lines": quote["lines"], "total_cents": quote["total_cents"], "total_brl": quote["total_brl"],
            "eta_minutes": quote["eta_minutes"],
        }

    def order_status(self, order_id: str) -> dict:
        order = self._get(order_id)
        status = self._status(order)
        remaining = 0
        if status not in {"cancelled", "delivered"}:
            remaining = max(0, math.ceil(order["eta_minutes"] - self._elapsed_minutes(order)))
        return {
            "order_id": order["order_id"], "status": status, "restaurant": order["restaurant"],
            "total_brl": order["total_brl"], "eta_minutes_remaining": remaining,
        }

    def cancel_order(self, order_id: str) -> dict:
        order = self._get(order_id)
        status = self._status(order)
        if status not in CANCELLABLE:
            raise ShopError(f"order {order['order_id']} can no longer be cancelled (status: {status})")
        order["cancelled"] = True
        return {"cancelled": True, "order_id": order["order_id"]}

    # --- internals -------------------------------------------------------------------------

    def _lines(self, items: list[tuple[int, int]]) -> list[dict]:
        if not items:
            raise ShopError("an order needs at least one item")
        merged: dict[int, int] = {}
        for item_id, quantity in items:
            merged[item_id] = merged.get(item_id, 0) + quantity  # the same item twice is one line
        if len(merged) > MAX_LINES:
            raise ShopError(f"an order can have at most {MAX_LINES} different items")
        lines = []
        for item_id, quantity in merged.items():
            item = self._menu.get(item_id)
            if item is None:
                raise ShopError(f"unknown item id: {item_id}")
            if not 1 <= quantity <= MAX_QUANTITY:
                raise ShopError(f"the quantity of '{item['name']}' must be between 1 and {MAX_QUANTITY}")
            lines.append({
                "item_id": item_id, "name": item["name"], "restaurant": item["restaurant"], "quantity": quantity,
                "unit_cents": item["price_cents"], "line_cents": item["price_cents"] * quantity,
            })
        return lines

    def _zone(self, zone: str) -> tuple[str, dict]:
        key = normalize(zone)
        if key not in self._zones:
            raise ShopError(f"unknown delivery zone: {zone!r}. Available zones: {', '.join(sorted(self._zones))}")
        return key, self._zones[key]

    def _get(self, order_id: str) -> dict:
        order = self._orders.get(str(order_id).strip().upper())
        if order is None:
            raise ShopError(f"order not found: {order_id}")
        return order

    def _elapsed_minutes(self, order: dict) -> float:
        return (self._clock() - order["created_at"]) / 60

    def _status(self, order: dict) -> str:
        if order["cancelled"]:
            return "cancelled"
        elapsed = self._elapsed_minutes(order)
        if elapsed < RECEIVED_UNTIL:
            return "received"
        if elapsed < PREPARING_UNTIL:
            return "preparing"
        if elapsed < order["eta_minutes"]:
            return "on_the_way"
        return "delivered"
