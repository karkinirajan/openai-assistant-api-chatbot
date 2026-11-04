# Lilac Chatbot

A customer-support chatbot. Customers sign up, log in and chat with **Jessica**, the Life in Lilac assistant.
Each reply is one call to the OpenAI Responses API, which can search a vector store (the shop's product
catalogue, or your own files) with `file_search`, and which answers in a structured form: the text for the
customer, plus an `is_order` flag and an `order_id` for replacement and order requests. Each customer has one
conversation, remembered between visits.

## Contents

1. [Features](#features)
2. [Quickstart](#quickstart)
3. [Configuration](#configuration)
4. [How a message is answered](#how-a-message-is-answered)
5. [Replacement requests](#replacement-requests)
6. [Project structure](#project-structure)
7. [Testing](#testing)
8. [Docker](#docker)
9. [Limits](#limits)
10. [Versions](#versions)
11. [License](#license)

More detail: [The knowledge base](docs/knowledge-base.md) and [Replacement requests](docs/replacement-requests.md).

## Features

* Sign-up, log-in, profile and chat pages; passwords are hashed, every POST carries a CSRF token, log-out is a POST.
* One OpenAI conversation per customer, kept in order by OpenAI; the messages are stored here too, so the page
  shows them again. The persona (`src/lilac_chatbot/data/persona.md`) is the original system prompt.
* The persona is told, on every request, the customer's first name, the part of the day and the day of the week
  (it uses the last for its "ships tomorrow, or Monday after Friday and Saturday" rule).
* Replies are requested as a structured output; text that still is not that JSON is shown as plain text.
* `lilac-chatbot replacements` lists the replies in which the assistant flagged a replacement or order request,
  and counts them by month.
* `lilac-chatbot init-knowledge --shopify` uploads the shop's active products to a new vector store.
* Strict Content-Security-Policy (nothing is loaded from another site, no inline script or style), HttpOnly /
  SameSite session cookies, `no-store` pages. The server never runs in debug mode.

## Quickstart

You need [uv](https://docs.astral.sh/uv/) and an OpenAI API key.

```bash
uv sync
cp .env.example .env                  # then fill it in (git-ignored, read from the current directory)
python -c "import secrets; print(secrets.token_urlsafe(32))"   # -> SECRET_KEY
uv run lilac-chatbot init-knowledge --shopify   # optional: prints VECTOR_STORE_ID=vs_... for your .env
uv run lilac-chatbot init-db          # creates the tables (the app also creates them on start)
uv run lilac-chatbot run              # development server on http://127.0.0.1:5003
```

`init-knowledge` needs `--shopify` (with `SHOPIFY_SHOP` and `SHOPIFY_ACCESS_TOKEN`) and/or `--file PATH`
(repeatable). Without a `VECTOR_STORE_ID` the chatbot still answers, from its instructions only.

## Configuration

Environment variables (`.env.example` lists them; a test keeps that file complete):

| Variable | Default | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | required | your OpenAI key |
| `SECRET_KEY` | required (web) | signs the session cookie, 16+ characters; it must stay the same between restarts |
| `OPENAI_MODEL` | `gpt-5.5` | model used for replies |
| `VECTOR_STORE_ID` | none | the vector store to search (`vs_...`) |
| `PUBLIC_URL` | `http://localhost:5003` | where users reach the app; `https://` makes the cookie `Secure` |
| `DATABASE_URL` | `sqlite:///chatbot.db` | SQLAlchemy URL |
| `TIMEZONE` | `America/Chicago` | zone for the greeting and the day of the week |
| `REQUEST_TIMEOUT` | `60` | seconds to wait for OpenAI |
| `MAX_OUTPUT_TOKENS`, `MAX_QUERY_CHARS` | `700`, `2000` | bounds on a reply and on a customer's message |
| `CHAT_PAUSE_SECONDS`, `CHAT_SECONDS_PER_WORD`, `CHAT_MAX_TYPING_SECONDS` | `10`, `0.66`, `30` | the typing behaviour of the chat page (`0` answers at once) |
| `SHOPIFY_SHOP`, `SHOPIFY_ACCESS_TOKEN`, `SHOPIFY_API_VERSION` | none, none, `2026-10` | only for `init-knowledge --shopify` |
| `OPENAI_BASE_URL` | none | for tests, proxies or an OpenAI-compatible server |

## How a message is answered

1. The browser posts the message (with the CSRF token) to `/chat`.
2. The customer's conversation is looked up, or created on first use (`conversations.create`).
3. `responses.create` is called with the persona and the context lines as `instructions`, the customer's words
   as `input`, the `conversation` id, the `file_search` tool on the vector store (if set) and the structured
   reply format. Only a hash of the customer's id is sent to OpenAI (`safety_identifier`), and only the first name.
4. Both sides of the exchange are saved (the flag and the order id with the assistant's message) and the answer
   is returned as JSON.

If OpenAI fails, the customer sees a generic message and nothing is saved; error text from OpenAI is never shown
or logged, because it can quote part of the API key.

## Replacement requests

**The persona tells the customer a replacement "has been arranged" and "will ship tomorrow", but nothing in this
project creates an order in Shopify.** The `is_order` flag is saved so that a person can act on it:

```bash
uv run lilac-chatbot replacements
# 2026-11-02 14:05  alice  order #1234  I've arranged a replacement for the rose candle ...
# By month: 2026-11: 1
```

## Project structure

```
src/lilac_chatbot/
  config.py       settings from the environment (secrets kept out of repr)
  persona.py      the persona, the per-request context (name, part of day, weekday), name cleaning
  assistant.py    SupportAssistant: new_conversation(), reply(); the structured reply and its parsing
  knowledge.py    create_knowledge_base(): upload files to a vector store
  shopify.py      read the active products (GraphQL Admin API) and write them as markdown
  models.py       User, ChatThread, ChatMessage (with is_order and order_id)
  views.py        routes, sessions, CSRF            app.py  application factory, security headers
  cli.py          lilac-chatbot run | init-db | init-knowledge | replacements
  data/           persona.md                        templates/, static/ (style.css, chat.js)
tests/            a fake OpenAI, a fake Shopify, unit and flow tests
docs/             the knowledge base, replacement requests
```

## Testing

```bash
uv run pytest -q -W error --cov
uv run ruff check . && uv run ruff format --check .
```

178 tests, 98 % line and branch coverage. Tests use an in-process fake OpenAI (`tests/fake_openai.py`) and a fake
Shopify, so they need no key and no network. **No live OpenAI or Shopify call has been made with this code**: there
was no key, only demo values. The app was also run under gunicorn against a local fake OpenAI over HTTP, and in a
real browser (screenshots, keyboard focus, contrast and overflow checks in both themes).

## Docker

```bash
docker build -t lilac-chatbot .
docker run -p 8000:8000 --env-file .env -v chatbot-data:/data lilac-chatbot   # PUBLIC_URL must match
```

The image runs gunicorn as an unprivileged user, creates the tables on start, keeps the SQLite file in the
`/data` volume and contains no `.env`.

## Limits

* Conversations are stored by OpenAI as well as here. There is no feature yet to delete a customer's conversation.
* The vector store is a snapshot: product availability is as of the last `init-knowledge --shopify`.
* Log-in attempts are not rate limited (put a rate limit in front of the app, or add one).
* The chatbot does not look up a customer's orders: it knows an order only from what the customer says.

## Versions

Python 3.13, Flask 3.1, openai 3.45. Details in [VERSIONS.md](VERSIONS.md); what changed from the first version
in [work-done.md](work-done.md).

## License

MIT, see [LICENSE](LICENSE).
