"""Settings, read from the environment.

The first version wrote an OpenAI key, a Shopify token and the Flask secret key in the source files. Nothing
secret is written in the code now, and secrets are kept out of ``repr`` so they do not reach logs.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# The model named in the OpenAI SDK's README at the time of writing. Set OPENAI_MODEL to use another one.
DEFAULT_MODEL = "gpt-5.5"
# Latest stable Admin API version according to Shopify's versioning page at the time of writing.
DEFAULT_SHOPIFY_API_VERSION = "2026-10"
DEFAULT_TIMEZONE = (
    "America/Chicago"  # the brief: "if we don't know the local time of the customer use central time"
)

_SHOP = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
_API_VERSION = re.compile(r"^\d{4}-\d{2}$")
_VECTOR_STORE = re.compile(r"^vs_[A-Za-z0-9_-]+$")


class ConfigError(Exception):
    """A setting is missing or invalid. The message names the variable, never its value."""


def _number(environ: Mapping[str, str], name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number") from None
    if value < minimum or value != value:  # the second test rejects NaN
        raise ConfigError(f"{name} must be at least {minimum:g}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    # repr=False on every secret: a Settings object ends up in logs and tracebacks
    openai_api_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    public_url: str = "http://localhost:5003"
    openai_model: str = DEFAULT_MODEL
    openai_base_url: str = ""
    vector_store_id: str = ""
    database_url: str = "sqlite:///chatbot.db"
    timezone: str = DEFAULT_TIMEZONE
    request_timeout: float = 60.0
    max_output_tokens: int = 700
    max_query_chars: int = 2000
    chat_pause_seconds: float = 10.0
    chat_seconds_per_word: float = 0.66
    chat_max_typing_seconds: float = 30.0
    shopify_shop: str = ""
    shopify_access_token: str = field(default="", repr=False)
    shopify_api_version: str = DEFAULT_SHOPIFY_API_VERSION

    @property
    def cookie_secure(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def shopify_configured(self) -> bool:
        return bool(self.shopify_shop and self.shopify_access_token)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, *, web: bool = True) -> Settings:
        """`web=False` is for command line jobs that only talk to OpenAI/Shopify (no cookie, no URL)."""
        environ = os.environ if environ is None else environ

        def get(name: str) -> str:
            return environ.get(name, "").strip()

        required = ["OPENAI_API_KEY"] + (["SECRET_KEY"] if web else [])
        missing = [n for n in required if not get(n)]
        if missing:
            raise ConfigError("Missing environment variables: " + ", ".join(missing))
        if web and len(get("SECRET_KEY")) < 16:
            raise ConfigError("SECRET_KEY must be at least 16 characters")

        public_url = (get("PUBLIC_URL") or "http://localhost:5003").rstrip("/")
        if not public_url.startswith(("http://", "https://")):
            raise ConfigError("PUBLIC_URL must start with http:// or https://")

        timezone = get("TIMEZONE") or DEFAULT_TIMEZONE
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise ConfigError("TIMEZONE must be an IANA name such as America/Chicago") from None

        vector_store = get("VECTOR_STORE_ID")
        if vector_store and not _VECTOR_STORE.match(vector_store):
            raise ConfigError("VECTOR_STORE_ID must look like vs_...")

        shop, token = get("SHOPIFY_SHOP").lower(), get("SHOPIFY_ACCESS_TOKEN")
        if bool(shop) != bool(token):
            raise ConfigError("Set both SHOPIFY_SHOP and SHOPIFY_ACCESS_TOKEN, or neither")
        if shop and not _SHOP.match(shop):
            # The token is sent to this host, so it must be a Shopify domain
            raise ConfigError("SHOPIFY_SHOP must be the shop's *.myshopify.com domain")
        shopify_version = get("SHOPIFY_API_VERSION") or DEFAULT_SHOPIFY_API_VERSION
        if not _API_VERSION.match(shopify_version):
            raise ConfigError("SHOPIFY_API_VERSION must look like 2026-10")

        return cls(
            openai_api_key=get("OPENAI_API_KEY"),
            secret_key=get("SECRET_KEY"),
            public_url=public_url,
            openai_model=get("OPENAI_MODEL") or DEFAULT_MODEL,
            openai_base_url=get("OPENAI_BASE_URL"),
            vector_store_id=vector_store,
            database_url=get("DATABASE_URL") or "sqlite:///chatbot.db",
            timezone=timezone,
            request_timeout=_number(environ, "REQUEST_TIMEOUT", 60.0, minimum=1),
            max_output_tokens=int(_number(environ, "MAX_OUTPUT_TOKENS", 700, minimum=16)),
            max_query_chars=int(_number(environ, "MAX_QUERY_CHARS", 2000, minimum=1)),
            chat_pause_seconds=_number(environ, "CHAT_PAUSE_SECONDS", 10.0),
            chat_seconds_per_word=_number(environ, "CHAT_SECONDS_PER_WORD", 0.66),
            chat_max_typing_seconds=_number(environ, "CHAT_MAX_TYPING_SECONDS", 30.0),
            shopify_shop=shop,
            shopify_access_token=token,
            shopify_api_version=shopify_version,
        )
