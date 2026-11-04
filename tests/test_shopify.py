import json

import httpx
import pytest

from lilac_chatbot.config import Settings
from lilac_chatbot.shopify import (
    MAX_PAGES,
    PRODUCTS_QUERY,
    ShopifyCatalog,
    ShopifyError,
    catalogue_markdown,
)

TOKEN = "demo-shop-token"


@pytest.fixture
def shop_settings(env):
    return Settings.from_env(
        {**env, "SHOPIFY_SHOP": "demo-shop.myshopify.com", "SHOPIFY_ACCESS_TOKEN": TOKEN}
    )


def node(title, status="ACTIVE", **extra):
    return {
        "id": f"gid://shopify/Product/{title}", "title": title, "handle": title.lower().replace(" ", "-"),
        "description": f"About {title}", "productType": "Candle", "vendor": "Lilac", "tags": ["soy"],
        "status": status, "totalInventory": 5,
        "priceRangeV2": {"minVariantPrice": {"amount": "12.0", "currencyCode": "USD"},
                         "maxVariantPrice": {"amount": "18.0", "currencyCode": "USD"}},
        **extra,
    }  # fmt: skip


def page(nodes, end=None):
    return {
        "data": {"products": {"nodes": nodes, "pageInfo": {"hasNextPage": end is not None, "endCursor": end}}}
    }


def catalog(settings, pages, seen=None):
    pages = list(pages)

    def handler(request):
        if seen is not None:
            seen.append(request)
        item = pages.pop(0) if len(pages) > 1 else pages[0]
        return item if isinstance(item, httpx.Response) else httpx.Response(200, json=item)

    return ShopifyCatalog(settings, httpx.Client(transport=httpx.MockTransport(handler)))


def test_the_request_goes_to_the_shops_admin_api_with_the_token_in_a_header(shop_settings):
    seen = []
    catalog(shop_settings, [page([node("Rose")])], seen).products()
    request = seen[0]
    assert str(request.url) == "https://demo-shop.myshopify.com/admin/api/2026-10/graphql.json"
    assert request.headers["x-shopify-access-token"] == TOKEN and TOKEN not in str(request.url)
    assert json.loads(request.content)["variables"] == {"cursor": None}


def test_the_query_asks_for_products_and_never_for_customers_or_orders():
    """The first version put every customer and order in a vector store the chatbot answered from."""
    lowered = PRODUCTS_QUERY.lower()
    assert "products(" in lowered
    for word in ("customer", "order", "email", "address", "phone"):
        assert word not in lowered


def test_pages_are_followed_with_the_cursor(shop_settings):
    seen = []
    products = catalog(
        shop_settings, [page([node("A")], "c1"), page([node("B")], "c2"), page([node("C")])], seen
    ).products()
    assert [p.title for p in products] == ["A", "B", "C"]
    assert [json.loads(r.content)["variables"]["cursor"] for r in seen] == [None, "c1", "c2"]


def test_only_active_products_are_kept(shop_settings):
    products = catalog(
        shop_settings, [page([node("Live"), node("Draft", "DRAFT"), node("Old", "ARCHIVED")])]
    ).products()
    assert [p.title for p in products] == ["Live"]


def test_a_repeated_cursor_ends_the_loop(shop_settings):
    seen = []
    catalog(shop_settings, [page([node("A")], "same")], seen).products()
    assert len(seen) == 2  # the second answer repeats the cursor it was asked with


def test_the_page_count_is_capped(shop_settings):
    seen = []
    counter = iter(range(10_000))

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=page([node("A")], f"c{next(counter)}"))

    ShopifyCatalog(shop_settings, httpx.Client(transport=httpx.MockTransport(handler))).products()
    assert len(seen) == MAX_PAGES


def test_a_product_is_read_into_plain_fields(shop_settings):
    (p,) = catalog(shop_settings, [page([node("Rose Candle")])]).products()
    assert (p.title, p.handle, p.product_type, p.vendor, p.tags) == (
        "Rose Candle",
        "rose-candle",
        "Candle",
        "Lilac",
        ("soy",),
    )
    assert (p.price_min, p.price_max, p.currency, p.in_stock) == ("12.0", "18.0", "USD", True)


def test_a_product_with_missing_fields_still_loads(shop_settings):
    (p,) = catalog(shop_settings, [page([{"title": "Bare", "status": "ACTIVE"}])]).products()
    assert p.title == "Bare" and p.price_min == "" and p.tags == () and p.in_stock is False


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_http_errors_name_the_status_and_nothing_else(shop_settings, status):
    response = httpx.Response(status, text=f"denied for token {TOKEN}")
    with pytest.raises(ShopifyError) as caught:
        catalog(shop_settings, [response]).products()
    assert str(status) in str(caught.value) and TOKEN not in str(caught.value)


def test_graphql_errors_come_with_http_200_and_are_reported_by_code(shop_settings):
    body = {"errors": [{"message": f"Access denied {TOKEN}", "extensions": {"code": "ACCESS_DENIED"}},
                       {"message": "x", "extensions": {"code": "THROTTLED"}}]}  # fmt: skip
    with pytest.raises(ShopifyError) as caught:
        catalog(shop_settings, [body]).products()
    assert (
        "ACCESS_DENIED" in str(caught.value)
        and "THROTTLED" in str(caught.value)
        and TOKEN not in str(caught.value)
    )


UNEXPECTED = [
    httpx.Response(200, text="<html>"),
    httpx.Response(200, json=["list"]),
    httpx.Response(200, json={"data": {"products": {"nodes": "no"}}}),
]


@pytest.mark.parametrize("body", UNEXPECTED)
def test_unexpected_answers_are_errors(shop_settings, body):
    with pytest.raises(ShopifyError):
        catalog(shop_settings, [body]).products()


def test_network_errors_name_only_their_kind(shop_settings):
    def boom(request):
        raise httpx.ConnectError(f"cannot reach {request.url} with {TOKEN}")

    with pytest.raises(ShopifyError) as caught:
        ShopifyCatalog(shop_settings, httpx.Client(transport=httpx.MockTransport(boom))).products()
    assert "ConnectError" in str(caught.value) and TOKEN not in str(caught.value)


def test_it_refuses_to_start_without_a_shop(settings):
    with pytest.raises(ShopifyError, match="not set"):
        ShopifyCatalog(settings)


def test_the_catalogue_markdown_describes_each_product(shop_settings):
    products = catalog(
        shop_settings, [page([node("Rose Candle"), node("Sold Out", totalInventory=0)])]
    ).products()
    text = catalogue_markdown(products, shop="demo-shop.myshopify.com")
    assert (
        "## Rose Candle" in text
        and "- Price: 12.0 to 18.0 USD" in text
        and "- Page: /products/rose-candle" in text
    )
    assert "In stock at export: yes" in text and "In stock at export: no" in text
    assert "may have changed since" in text
    assert "inventory" not in text.lower()  # the stock level is a snapshot: only yes/no is exported


def test_a_single_price_is_shown_once_and_merchant_text_is_one_clean_line(shop_settings):
    one_price = {"amount": "9.5", "currencyCode": "EUR"}
    nasty = node(
        "T\nitle",
        description="Line one\n\nline two\u202e\x00 end",
        priceRangeV2={"minVariantPrice": one_price, "maxVariantPrice": one_price},
    )
    text = catalogue_markdown(catalog(shop_settings, [page([nasty])]).products())
    assert "- Price: 9.5 EUR" in text and "9.5 to" not in text
    assert "## T itle" in text and "Line one line two end" in text
    assert "\u202e" not in text and "\x00" not in text


def test_an_empty_catalogue_is_still_a_document():
    assert catalogue_markdown([]).startswith("# Product catalogue")
