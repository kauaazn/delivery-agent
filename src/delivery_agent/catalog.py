"""Demo data: fictional restaurants, delivery zones and coupons.

Everything here is made up for the demo and not affiliated with any real company.
Money is always integer cents: floats and money do not mix.
"""
from __future__ import annotations

TAGS = {"vegan", "vegetarian", "gluten_free", "spicy"}


def _item(item_id: int, restaurant: str, category: str, name: str, description: str, price_cents: int, *tags: str) -> dict:
    assert set(tags) <= TAGS, f"unknown tag in item {item_id}"
    return {
        "id": item_id, "restaurant": restaurant, "category": category, "name": name,
        "description": description, "price_cents": price_cents, "tags": sorted(tags),
    }


MENU: list[dict] = [
    # Forno Doce: pizzas
    _item(1, "Forno Doce", "pizza", "Pizza Margherita", "Molho de tomate, mussarela e manjericão.", 4200, "vegetarian"),
    _item(2, "Forno Doce", "pizza", "Pizza Calabresa", "Calabresa, cebola e mussarela.", 4600),
    _item(3, "Forno Doce", "pizza", "Pizza Quatro Queijos", "Mussarela, provolone, gorgonzola e parmesão.", 5200, "vegetarian"),
    _item(4, "Forno Doce", "pizza", "Pizza Vegana de Cogumelos", "Cogumelos, queijo vegetal e rúcula.", 5400, "vegan", "vegetarian"),
    _item(5, "Forno Doce", "pizza", "Calzone de Frango", "Frango desfiado com catupiry.", 3800),
    _item(6, "Forno Doce", "bebida", "Refrigerante 2L", "Cola, guaraná ou limão.", 1200, "vegan", "vegetarian", "gluten_free"),
    # Sushi do Porto: japonesa
    _item(7, "Sushi do Porto", "japonesa", "Combo Sushi 20 peças", "Salmão, atum e kani.", 6800),
    _item(8, "Sushi do Porto", "japonesa", "Temaki de Salmão", "Cone de alga com salmão e cream cheese.", 2800),
    _item(9, "Sushi do Porto", "japonesa", "Hot Roll 8 unidades", "Salmão empanado e frito.", 3200),
    _item(10, "Sushi do Porto", "japonesa", "Yakisoba de Legumes", "Macarrão oriental com legumes salteados.", 3600, "vegetarian"),
    _item(11, "Sushi do Porto", "japonesa", "Shimeji na Manteiga", "Cogumelos salteados na manteiga.", 3000, "vegetarian", "gluten_free"),
    _item(12, "Sushi do Porto", "bebida", "Chá Gelado", "Chá de pêssego.", 900, "vegan", "vegetarian", "gluten_free"),
    # Burger Bairro: hambúrgueres
    _item(13, "Burger Bairro", "hamburguer", "Cheeseburger Clássico", "Blend 150g, queijo cheddar e picles.", 2900),
    _item(14, "Burger Bairro", "hamburguer", "Burger Duplo Bacon", "Dois blends, bacon crocante e cheddar.", 3900),
    _item(15, "Burger Bairro", "hamburguer", "Burger de Frango Crocante", "Frango empanado, alface e maionese.", 3100),
    _item(16, "Burger Bairro", "hamburguer", "Burger Picante da Casa", "Blend 150g, jalapeño e molho de pimenta.", 3400, "spicy"),
    _item(17, "Burger Bairro", "acompanhamento", "Batata Frita Grande", "Porção grande, sequinha.", 1800, "vegan", "vegetarian", "gluten_free"),
    _item(18, "Burger Bairro", "sobremesa", "Milkshake de Chocolate", "400ml com calda de chocolate.", 1900, "vegetarian"),
    # Verde Vivo: saudável
    _item(19, "Verde Vivo", "saudavel", "Bowl de Grão-de-Bico", "Grão-de-bico, quinoa, legumes assados e tahine.", 3400, "vegan", "vegetarian", "gluten_free"),
    _item(20, "Verde Vivo", "saudavel", "Burger de Lentilha", "Hambúrguer de lentilha com pão integral.", 3300, "vegan", "vegetarian"),
    _item(21, "Verde Vivo", "saudavel", "Salada Mediterrânea", "Folhas, tomate, pepino, azeitona e azeite.", 2900, "vegan", "vegetarian", "gluten_free"),
    _item(22, "Verde Vivo", "saudavel", "Wrap de Falafel", "Falafel, homus e molho de pimenta.", 2700, "vegan", "vegetarian", "spicy"),
    _item(23, "Verde Vivo", "bebida", "Suco Verde Detox", "Couve, limão, gengibre e maçã.", 1400, "vegan", "vegetarian", "gluten_free"),
    _item(24, "Verde Vivo", "sobremesa", "Brownie Vegano", "Chocolate meio amargo, sem leite e sem ovos.", 1600, "vegan", "vegetarian"),
]

# Delivery zones: fee in cents and the estimated delivery time in minutes.
ZONES: dict[str, dict] = {
    "centro": {"fee_cents": 500, "eta_minutes": 30},
    "norte": {"fee_cents": 800, "eta_minutes": 40},
    "sul": {"fee_cents": 800, "eta_minutes": 40},
    "leste": {"fee_cents": 1000, "eta_minutes": 50},
    "oeste": {"fee_cents": 1000, "eta_minutes": 50},
}

# Coupons: either a percentage off the subtotal or free delivery, with a minimum subtotal.
COUPONS: dict[str, dict] = {
    "PRIMEIRA10": {"kind": "percent", "value": 10, "min_subtotal_cents": 3000},
    "FRETEGRATIS": {"kind": "free_delivery", "min_subtotal_cents": 6000},
}
