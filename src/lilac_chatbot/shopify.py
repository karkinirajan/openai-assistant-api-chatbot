"""The Shopify product catalogue, as text the assistant can search.

The first version loaded every customer, order and product of the shop (names, addresses, emails, order
history) into a vector store that the chatbot answered from, so any signed-in customer could ask it about
other customers. Only products are read now, and only the active ones. The GraphQL Admin API is used because
Shopify's REST Admin API has been a legacy API since 2024-10-01.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

import httpx

from .config import Settings

logger = logging.getLogger(__name__)

MAX_PAGES = 100  # 100 products a page: a catalogue of 10,000 products at most

PRODUCTS_QUERY = """
query Products($cursor: String) {
  products(first: 100, after: $cursor) {
    nodes {
      id
      title
      handle
      description
      productType
      vendor
      tags
      status
      totalInventory
      priceRangeV2 {
        minVariantPrice { amount currencyCode }
        maxVariantPrice { amount currencyCode }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


class ShopifyError(Exception):
    """Shopify refused the request or answered something unexpected. Holds no token or response body."""


@dataclass(frozen=True, slots=True)
class Product:
    title: str
    handle: str
    description: str
    product_type: str
    vendor: str
    tags: tuple[str, ...]
    price_min: str
    price_max: str
    currency: str
    in_stock: bool


def _text(value: object) -> str:
    """Merchant-written text on one line, without control characters."""
    text = str(value or "")
    kept = "".join(
        " " if c.isspace() else c for c in text if c.isspace() or not unicodedata.category(c).startswith("C")
    )
    return re.sub(r" {2,}", " ", kept).strip()


def _product(node: dict) -> Product:
    price = node.get("priceRangeV2") or {}
    low, high = price.get("minVariantPrice") or {}, price.get("maxVariantPrice") or {}
    return Product(
        title=_text(node.get("title")),
        handle=_text(node.get("handle")),
        description=_text(node.get("description")),
        product_type=_text(node.get("productType")),
        vendor=_text(node.get("vendor")),
        tags=tuple(_text(t) for t in node.get("tags") or [] if _text(t)),
        price_min=_text(low.get("amount")),
        price_max=_text(high.get("amount")),
        currency=_text(low.get("currencyCode")),
        in_stock=(node.get("totalInventory") or 0) > 0,
    )


class ShopifyCatalog:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if not settings.shopify_configured:
            raise ShopifyError("SHOPIFY_SHOP and SHOPIFY_ACCESS_TOKEN are not set")
        self._url = f"https://{settings.shopify_shop}/admin/api/{settings.shopify_api_version}/graphql.json"
        self._token = settings.shopify_access_token
        self._client = client or httpx.Client(timeout=settings.request_timeout)

    def _post(self, cursor: str | None) -> dict:
        try:
            response = self._client.post(
                self._url,
                json={"query": PRODUCTS_QUERY, "variables": {"cursor": cursor}},
                # In a header, never in the URL: URLs end up in logs and tracebacks
                headers={"X-Shopify-Access-Token": self._token},
            )
        except httpx.HTTPError as exc:
            raise ShopifyError(f"Shopify request failed ({type(exc).__name__})") from None
        if response.status_code != 200:
            raise ShopifyError(f"Shopify answered HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            raise ShopifyError("Shopify answered something that is not JSON") from None
        if not isinstance(body, dict):
            raise ShopifyError("Shopify answered something unexpected")
        if body.get("errors"):
            # GraphQL errors come with HTTP 200. Only their codes are reported, never their text.
            codes = sorted(
                {
                    str((e.get("extensions") or {}).get("code") or "error")
                    for e in body["errors"]
                    if isinstance(e, dict)
                }
            )
            raise ShopifyError("Shopify reported errors: " + ", ".join(codes or ["error"]))
        return body

    def products(self) -> list[Product]:
        """The active products, all pages."""
        found: list[Product] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            connection = ((self._post(cursor).get("data") or {}).get("products")) or {}
            nodes = connection.get("nodes")
            if not isinstance(nodes, list):
                raise ShopifyError("Shopify answered no product list")
            found += [_product(n) for n in nodes if isinstance(n, dict) and n.get("status") == "ACTIVE"]
            page = connection.get("pageInfo") or {}
            next_cursor = page.get("endCursor")
            if not page.get("hasNextPage") or not next_cursor or next_cursor == cursor:
                return found
            cursor = next_cursor
        logger.warning("Stopped after %d pages of products", MAX_PAGES)
        return found


def catalogue_markdown(products: list[Product], *, shop: str = "") -> str:
    """The catalogue as a markdown file for the vector store. Stock is a snapshot of the moment of export."""
    lines = ["# Product catalogue", ""]
    if shop:
        lines += [f"Shop: {shop}", ""]
    lines += ["Availability is as of the export and may have changed since.", ""]
    for p in products:
        lines.append(f"## {p.title}")
        if p.product_type:
            lines.append(f"- Type: {p.product_type}")
        if p.vendor:
            lines.append(f"- Brand: {p.vendor}")
        if p.price_min:
            price = (
                p.price_min
                if p.price_min == p.price_max or not p.price_max
                else f"{p.price_min} to {p.price_max}"
            )
            lines.append(f"- Price: {price} {p.currency}".rstrip())
        lines.append(f"- In stock at export: {'yes' if p.in_stock else 'no'}")
        if p.tags:
            lines.append(f"- Tags: {', '.join(p.tags)}")
        if p.handle:
            lines.append(f"- Page: /products/{p.handle}")
        if p.description:
            lines += ["", p.description]
        lines.append("")
    return "\n".join(lines)
