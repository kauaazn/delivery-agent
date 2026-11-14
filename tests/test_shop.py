"""The business rules, with no AI involved."""
import pytest

from delivery_agent.shop import ShopError, brl, normalize


# --- helpers ----------------------------------------------------------------------------------


def test_brl_formats_cents_like_brazilian_reais():
    assert brl(5490) == "R$ 54,90"
    assert brl(5) == "R$ 0,05"
    assert brl(123456) == "R$ 1.234,56"


def test_normalize_strips_accents_and_case():
    assert normalize("  Mediterrânea ") == "mediterranea"


# --- searching the menu -----------------------------------------------------------------------


def test_search_matches_a_word_in_the_name(shop):
    assert [item["name"] for item in shop.search("calabresa")] == ["Pizza Calabresa"]


def test_search_ignores_accents_and_case(shop):
    assert shop.search("MEDITERRANEA")[0]["name"] == "Salada Mediterrânea"


def test_search_ranks_a_name_hit_above_a_description_hit(shop):
    assert shop.search("queijo")[0]["name"] == "Pizza Quatro Queijos"


def test_search_filters_by_tags(shop):
    assert [item["name"] for item in shop.search("pizza", tags=["vegan"])] == ["Pizza Vegana de Cogumelos"]


def test_search_filters_by_price(shop):
    cheap = shop.search("burger", max_price_cents=3000)
    assert cheap[0]["name"] == "Cheeseburger Clássico"  # the best match is also under R$ 30,00
    assert all(item["price_cents"] <= 3000 for item in cheap)
    assert "Burger Duplo Bacon" not in [item["name"] for item in cheap]  # R$ 39,00 is over the limit


def test_search_returns_prices_in_cents_and_reais(shop):
    item = shop.search("margherita")[0]
    assert item["price_cents"] == 4200 and item["price_brl"] == "R$ 42,00"


def test_search_with_no_match_returns_an_empty_list(shop):
    assert shop.search("lasanha") == []


def test_search_respects_the_limit(shop):
    assert len(shop.search("pizza", limit=2)) == 2


def test_search_needs_a_meaningful_word(shop):
    with pytest.raises(ShopError, match="meaningful word"):
        shop.search("de a")


# --- pricing ----------------------------------------------------------------------------------


def test_quote_adds_the_items_and_the_zone_fee(shop):
    quote = shop.quote([(1, 2)], "centro")
    assert quote["subtotal_cents"] == 8400
    assert quote["delivery_fee_cents"] == 500
    assert quote["total_cents"] == 8900
    assert quote["total_brl"] == "R$ 89,00"
    assert quote["eta_minutes"] == 30
    assert quote["restaurant"] == "Forno Doce"


def test_quote_merges_the_same_item_listed_twice(shop):
    quote = shop.quote([(1, 1), (1, 1)], "centro")
    assert len(quote["lines"]) == 1 and quote["lines"][0]["quantity"] == 2


def test_quote_accepts_the_zone_in_any_case(shop):
    assert shop.quote([(1, 1)], "  CENTRO ")["zone"] == "centro"


def test_quote_rejects_items_from_two_restaurants(shop):
    with pytest.raises(ShopError, match="one restaurant"):
        shop.quote([(1, 1), (8, 1)], "centro")


@pytest.mark.parametrize(
    "items, zone, message",
    [
        ([], "centro", "at least one item"),
        ([(999, 1)], "centro", "unknown item"),
        ([(1, 0)], "centro", "quantity"),
        ([(1, 11)], "centro", "quantity"),
        ([(1, 6), (1, 6)], "centro", "quantity"),  # the same item twice adds up to 12
        ([(i, 1) for i in range(1, 12)], "centro", "at most"),  # 11 different items
        ([(1, 1)], "marte", "unknown delivery zone"),
    ],
)
def test_quote_rejects_invalid_orders(shop, items, zone, message):
    with pytest.raises(ShopError, match=message):
        shop.quote(items, zone)


# --- coupons ----------------------------------------------------------------------------------


def test_percent_coupon_discounts_the_subtotal_only(shop):
    quote = shop.quote([(1, 1)], "centro", "primeira10")  # coupon codes are case-insensitive
    assert quote["discount_cents"] == 420
    assert quote["total_cents"] == 4200 + 500 - 420
    assert quote["coupon"] == "PRIMEIRA10"


def test_free_delivery_coupon_removes_the_fee(shop):
    quote = shop.quote([(1, 2)], "centro", "FRETEGRATIS")
    assert quote["delivery_fee_cents"] == 0 and quote["total_cents"] == 8400


def test_a_coupon_below_its_minimum_is_rejected(shop):
    with pytest.raises(ShopError, match="at least R\\$ 30,00"):
        shop.quote([(6, 1)], "centro", "PRIMEIRA10")


def test_an_unknown_coupon_is_rejected(shop):
    with pytest.raises(ShopError, match="unknown coupon"):
        shop.quote([(1, 1)], "centro", "DESCONTAO")


# --- orders -----------------------------------------------------------------------------------


def test_orders_get_sequential_ids_and_are_priced_by_the_shop(shop):
    first = shop.place_order([(1, 2)], "centro", "Ana")
    second = shop.place_order([(8, 1)], "sul", "Bruno")
    assert (first["order_id"], second["order_id"]) == ("ORD-1001", "ORD-1002")
    assert first["total_cents"] == 8900
    assert shop.order_count == 2


def test_an_order_needs_a_customer_name(shop):
    with pytest.raises(ShopError, match="name"):
        shop.place_order([(1, 1)], "centro", "   ")


def test_a_rejected_order_creates_nothing(shop):
    with pytest.raises(ShopError):
        shop.place_order([(999, 1)], "centro", "Ana")
    assert shop.order_count == 0


def test_order_ids_ignore_case_and_spaces(shop):
    shop.place_order([(1, 1)], "centro", "Ana")
    assert shop.order_status(" ord-1001 ")["order_id"] == "ORD-1001"


def test_an_unknown_order_id_is_an_error(shop):
    with pytest.raises(ShopError, match="order not found"):
        shop.order_status("ORD-9999")


# --- time: statuses follow the clock ----------------------------------------------------------


def test_order_status_follows_the_clock(shop, clock):
    order_id = shop.place_order([(1, 1)], "centro", "Ana")["order_id"]  # the centro zone takes 30 minutes
    assert shop.order_status(order_id)["status"] == "received"
    clock.advance(5)
    assert shop.order_status(order_id)["status"] == "preparing"
    clock.advance(15)
    on_the_way = shop.order_status(order_id)
    assert on_the_way["status"] == "on_the_way" and on_the_way["eta_minutes_remaining"] == 10
    clock.advance(15)
    delivered = shop.order_status(order_id)
    assert delivered["status"] == "delivered" and delivered["eta_minutes_remaining"] == 0


def test_cancel_works_while_the_order_is_being_prepared(shop, clock):
    order_id = shop.place_order([(1, 1)], "centro", "Ana")["order_id"]
    clock.advance(5)
    assert shop.cancel_order(order_id) == {"cancelled": True, "order_id": order_id}
    assert shop.order_status(order_id)["status"] == "cancelled"


def test_cancel_is_refused_once_the_order_is_on_the_way(shop, clock):
    order_id = shop.place_order([(1, 1)], "centro", "Ana")["order_id"]
    clock.advance(20)
    with pytest.raises(ShopError, match="can no longer be cancelled"):
        shop.cancel_order(order_id)
    assert shop.order_status(order_id)["status"] == "on_the_way"


def test_cancelling_twice_is_refused(shop):
    order_id = shop.place_order([(1, 1)], "centro", "Ana")["order_id"]
    shop.cancel_order(order_id)
    with pytest.raises(ShopError, match="can no longer be cancelled"):
        shop.cancel_order(order_id)
