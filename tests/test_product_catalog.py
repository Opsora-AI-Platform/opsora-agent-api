import json
from pathlib import Path


CATALOG = Path(__file__).parents[1] / "config" / "product_catalog.json"


def test_catalog_is_valid_and_unique():
    data = json.loads(CATALOG.read_text())
    products = data["products"]
    slugs = [p["slug"] for p in products]
    assert len(slugs) == len(set(slugs))
    assert data["currency"] == "IDR"


def test_active_subscription_prices_match_store_catalog():
    expected = {
        "opsora-free": 0,
        "opsora-basic": 49000,
        "opsora-pro": 149000,
        "opsora-max": 299000,
    }
    for product in json.loads(CATALOG.read_text())["products"]:
        if product["slug"] in expected:
            assert product["status"] == "active"
            assert product["billing_interval"] == "month"
            assert product["price_idr"] == expected[product["slug"]]
            assert product["shopify_product_id"].startswith("gid://shopify/Product/")


def test_templates_are_not_sellable_without_fulfillment():
    for product in json.loads(CATALOG.read_text())["products"]:
        if product["category"] == "template":
            assert product["status"] == "draft"
            assert product["price_idr"] is None
            assert product["entitlement_key"].startswith("product:")
