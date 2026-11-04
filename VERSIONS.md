# Versions

Exact versions of every locked package are in `uv.lock`; these are the ones that matter.

| Component | Version | Pinned in |
|---|---|---|
| Python | 3.13 (3.13.18 used for the tests) | `.python-version`, `requires-python = ">=3.13"` |
| openai (Python SDK) | 3.45.0 (`>=3.42`) | `pyproject.toml`, `uv.lock` |
| pydantic | 2.14.2 (`>=2.10`) | `pyproject.toml`, `uv.lock` |
| Flask | 3.1.3 (`>=3.1`) | `pyproject.toml`, `uv.lock` |
| Flask-SQLAlchemy / SQLAlchemy | 3.1.1 / 2.1.8 | `uv.lock` |
| Werkzeug / Jinja2 | 3.1.9 / 3.1.6 | `uv.lock` (via Flask) |
| httpx | 0.28.1 (`>=0.28`) | `pyproject.toml`, `uv.lock` |
| python-dotenv / gunicorn | 1.2.4 / 26.2.0 | `uv.lock` |
| pytest / pytest-cov / ruff | 9.2.0 / 7.1.0 / 0.17.3 | dev group |
| uv | 0.13.7 locally, 0.13.6 in the Dockerfile | used to build the lock |
| Shopify Admin API | 2026-10 | `SHOPIFY_API_VERSION` (default) |
| OpenAI model | `gpt-5.5` | `OPENAI_MODEL` (default) |

## Where the less obvious ones come from

* **OpenAI API:** the Responses and Conversations APIs, which OpenAI's migration guide
  (<https://developers.openai.com/api/docs/assistants/migration>) names as the replacement for the Assistants API
  (sunset on 2026-08-26). This project never called the Assistants API (its `assistant_id` and `client` were
  unused leftovers), but the structure it needs (a conversation, a response) is the one the guide describes. The
  guide does not cover `file_search`, vector stores or structured outputs; those calls follow the signatures of
  the installed SDK, checked in code, not a live call.
* **Model:** `gpt-5.5` is the model named in the OpenAI SDK's README at the time of writing (the same default as
  the `news-summarizer` project). The migration guide's own examples use a different model name, so treat the
  default as a starting point and set `OPENAI_MODEL`. The old code used `gpt-4-0125-preview` at temperature 0.
* **Shopify:** 2026-10 is listed as the latest stable Admin API version, released 2026-10-01, by Shopify's
  versioning page (read through a web search summary, not fetched in full). The product fields used appear in the
  2026-10 GraphQL reference (checked by documentation search). The REST Admin API has been a legacy API since
  2024-10-01, so the GraphQL Admin API is used. The old code used API version 2023-01.

## What the first version ran on

Unpinned: a 139-line `pip freeze` (not read in detail). The code used LangChain (`langchain`, `langchain_community`,
`langchain_openai`) with Chroma, the Airbyte Shopify loader, the `ShopifyAPI` library, Flask with Flask-SQLAlchemy,
and Bootstrap 5.1.3 and jQuery 3.6.0 from CDNs. The README listed Python 3.8 or above, Flask-CORS and `requests`,
which the code did not use. All of that is replaced by the seven direct dependencies in `pyproject.toml`.
