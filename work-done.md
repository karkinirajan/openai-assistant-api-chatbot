# Work done on openai-assistant-api-chatbot (branch `chore/modernize`)

Local commit only; nothing was pushed. The first version was a small Flask chatbot (Life in Lilac, "Jessica") on
LangChain, Chroma and a download of the whole Shopify shop. It is rebuilt as a small tested package on the OpenAI
Responses API. It is a later cut of the same project as `openai-assistant-api`, and the two now share most of their
design and several modules (see [Relationship to the other repo](#relationship-to-openai-assistant-api)).

## Read this first: rotate these

They are in the git history (every code commit: `90f8727`, `9140fbc`, `4a4df43`, `46863a3`, `51b50bd`), not in the
new code. Removing them from the files does not remove them from history.

| What | Where in history | Do |
|---|---|---|
| **OpenAI API key** | `main.py`, all 5 code commits | revoke it at platform.openai.com/api-keys and look at its usage for calls you do not recognise |
| **Shopify Admin API access token**, and the shop's `*.myshopify.com` domain | `utils.py`, all 5 code commits | revoke or regenerate the token in the Shopify admin. It was used to read customers, orders and products; the scopes it was granted were not checked. The domain is an identifier, not a secret |
| **Flask `secret_key`** | `main.py`, all 5 code commits | anyone with it can forge a login session of a deployment that used it; use a new `SECRET_KEY` |

**These are the same three values as in `openai-assistant-api`** (compared by hash, nothing printed): one rotation
covers both repos. No runtime file (database, vector store) was ever tracked here, and there is no LangSmith key.
Rewriting the 6-commit history with `git filter-repo` is possible after rotation; only you can push it.

## What was there

* 6 commits (2024-03-01 twice, 2024-07-12, 2025-04-16 twice, 2025-04-21; the last four are titled "Update README.md"); 13
  tracked files, 1,317 lines: `main.py` (337), `utils.py` (177), `prompt.py` (126), six templates, a 139-line
  `pip freeze` and a 128-line README.
* `main.py`: a Flask app with sign-up, log-in, profile and chat, and models for users, a chat thread per user and
  chat messages. `utils.py`: the Shopify download (customers, orders and products through the Airbyte loader), a
  Chroma vector store and a LangChain `ConversationalRetrievalChain` on `gpt-4-0125-preview` at temperature 0.
  `prompt.py`: the system prompt of the persona (860 words).
* The six templates are **byte-identical** to the ones in `openai-assistant-api`.

## Findings in the first version

| Where | What was wrong |
|---|---|
| `main.py`, `utils.py` | an OpenAI key, a Shopify token and the Flask `secret_key` written in the source |
| `main.py` | `client = openai.OpenAI(...)` and `assistant_id` were never used: despite its name the project never called the Assistants API |
| `get_chat_history_concatenated` | ordered the messages **by sender first** and joined them per sender, so the model was given all of the customer's messages followed by all of the assistant's: the conversation was scrambled. The assistant's side was the raw JSON string it had returned |
| chat route | `json.loads(ass_response)` raised an error (a 500) whenever the model's text was not valid JSON, **after** the messages had already been saved |
| `utils.py` | the Shopify download ran at import time. `make_chain()` ran on every question and added **every chunk to the persistent Chroma store again**: duplicates grew with each question, and each one was embedded again |
| `utils.py` | `part_of_day` and `day_of_week` were worked out once, at import: a server left running showed the greeting and the ship day of the moment it started |
| Shopify + RAG | loaded **every customer, order and product** into the vector store the chatbot answered from: any signed-in customer could ask it about other customers |
| the persona (`prompt.py`) | tells the customer "I've arranged for a replacement... It will ship tomorrow", but nothing in the code ever creates an order: `is_order` was parsed and ignored |
| `main.py` | `app.run(debug=True)`, `GET /logout`, no CSRF protection on any form, a bare `logged_in` session flag, a duplicated `@app.route("/chat")`, `datetime.utcnow()`, `print()` of chat histories; `get_response` took an `email` and a `thread_id` and used neither |
| `utils.py` | deleted a file named `file::memory:?cache=shared` at import; Shopify API version 2023-01 |
| `templates/` | Bootstrap and jQuery from CDNs, inline `<script>` and `<style>`, and the chat script waited a hard-coded 10 seconds **before sending the request** |
| README | said `python app.py` (there is none), listed Flask-CORS and `requests` (unused), Python 3.8+ and `FLASK_ENV` |

## What was done, file by file

| First version | Now |
|---|---|
| `main.py` | `app.py` (factory, headers), `views.py` (routes, sessions, CSRF), `models.py`, `config.py`, `cli.py` |
| `prompt.py` | the persona moved **unchanged** to `src/lilac_chatbot/data/persona.md`, except the template plumbing at its end (the retrieved context, the chat history, the name, the part of the day and the weekday). `persona.py` writes the last three below it on every request |
| `utils.py` | `assistant.py` (one `responses.create` call, `file_search`, structured reply), `knowledge.py` (vector store upload), `shopify.py` (active **products only**, GraphQL Admin API 2026-10, token in a header). LangChain, Chroma and the Airbyte loader are gone |
| `templates/*` (6) | `src/lilac_chatbot/templates/` rewritten without inline code or CDNs; `static/style.css` (light and dark), `static/chat.js` |
| `requirements.txt` (139 lines) | `pyproject.toml` + `uv.lock` (Python 3.13; 7 direct dependencies) |
| `README.md` | rewritten |
| (new) | `.env.example`, `.gitignore`, `Dockerfile`, `.dockerignore`, `.github/workflows/ci.yml`, `VERSIONS.md`, `docs/` (2 pages), 183 tests |

### Behaviour that differs from the first version

* The vector store can hold the shop's **active products** and files you give it. **Customers and orders are not
  indexed**, so the chatbot can no longer quote another customer's data. It also can no longer find a customer's
  order "from the context" (a rule in the persona that relied on it): it knows an order only from what the
  customer says.
* The conversation is kept by OpenAI's Conversations API, **in order** (the old history was scrambled). The page
  also shows the stored messages again.
* The persona's context is written **per request** (the old values were frozen at import). The model is told the
  customer's **first name** only; the old code passed the full name and an unused email.
* The reply is requested as a structured output. The customer sees `answer`; the flag and the order id are stored
  with the message. A reply that is not that JSON is shown as plain text instead of causing an error. The flag is
  read strictly (`"yes"` or `1` is not `true`).
* Replies are stored without control and format characters (line breaks, tabs and emoji joiners are kept). An
  automated security review of the first commit found that `replacements` printed the start of a reply to the
  terminal as it was, so an ESC sequence written by the model (which a customer can steer) would have reached an
  operator's terminal. The reply is now cleaned when it is stored and again when it is printed.
* New: `lilac-chatbot replacements` lists the flagged replies and counts them by month. It is a work list: the
  persona's promise of a replacement still has nobody behind it.
* The chat page starts the request at once and runs the 10-second pause alongside it. The brief's per-word typing
  delay is implemented, as in the sibling, and all three delays are settings.
* Sign-up: passwords of 10 to 128 characters; usernames of 3 to 40 characters; usernames and emails are stored in
  lower case and compared without regard to case. Log-out is a POST with a CSRF token. A failed log-in is a 401.
* The default model is `gpt-5.5` (the old chain used `gpt-4-0125-preview`). **No temperature is set** (the old
  chain used 0): the new request leaves it to the model's default.

## Relationship to `openai-assistant-api`

The two repos are two cuts of one project: identical templates, the same persona (this one's prompt is the later and
longer), the same credentials. This rebuild reuses the architecture and several modules of the other one
(`config`, `app`, `views`, `knowledge`, `shopify`, the templates, the static files and most of the tests), adapted
here for the persona's context, the structured reply and the `replacements` report. Separate repositories cannot
share code without a shared package, so those modules now exist twice. **If both are kept, one should probably be
archived, or the shared part moved into a package.**

## Verified (commands actually run)

| Check | Result |
|---|---|
| `pytest -q -W error --cov` | 183 passed (warnings are errors); 98 % line and branch coverage |
| mutation check | 49 defects reintroduced one at a time (no CSRF check, a conversation shared between customers, an open redirect, a password stored in clear, no hash check for unknown accounts, raw OpenAI error text to the user, the Shopify token in the URL, customers requested from Shopify, the flag never stored, lax parsing of the flag, the structured format not requested, a non-JSON answer raising an error again, the weekday off by one, the last name sent to OpenAI, the report listing unflagged replies, ...; the three that undo the terminal-escape fix included): the suite failed for all 49; files restored afterwards |
| `ruff check`, `ruff format --check` | pass (rules `E F I B UP SIM S BLE RUF`) |
| the app under `gunicorn` and the CLI as separate processes against a local fake OpenAI over HTTP | `init-knowledge` (with a file, and refused with nothing to upload), sign-up and log-in of two customers, separate conversations, no history shown across customers, the structured format and the `file_search` tool requested, the input equal to the customer's words, first name and weekday in the instructions, no last name sent, hashed customer id, a flagged request through to `replacements`, **no plaintext password and no API key in the database or logs** |
| real browser (Chromium via Playwright): light and dark, 375/768/1280 px | the same templates and styles as in the sibling; the full check was run again against this app: all pages and chat states, no horizontal overflow, text contrast at least 4.5:1 and links 6.45:1 / 8.54:1, native focus rings, chat box focused on arrival |
| `docker build --no-cache`, then run | image 285 MB, user `app`, `/healthz` ok, tables created in `/data`, persona packaged, no `.env` inside, a flagged request answered through the fake |
| secret scan of the tree being committed | nothing found; history scan produced the list above |

## Not verified

* **No live OpenAI or Shopify call was made**: no credentials, only demo values and fakes. The Responses and
  Conversations calls follow the SDK's types and OpenAI's migration guide, which says nothing about `file_search`,
  vector stores or structured outputs. Whether the live API accepts `text.format` (a strict JSON schema) together
  with `file_search`, a `conversation` and `safety_identifier` was not checked; if it does not, the call fails and
  the customer sees the generic error.
* Whether the model follows the persona and fills the flag sensibly was not evaluated: that needs a live model.
* The Shopify product query was checked against the 2026-10 documentation, not run against a shop. The token needs
  the `read_products` scope.
* The default model `gpt-5.5` is the SDK README's; OpenAI's migration guide uses another name in its examples.
* GitHub Actions has not run (the same commands were run locally).

## Questions for the owner

1. **The persona promises a replacement that nobody creates.** Should it stop making the promise until an order
   can be created, or is someone working from `lilac-chatbot replacements`?
2. The persona says to find the order id "from the context" when the customer cannot give it. That needed every
   customer's orders in a shared index. A safe version looks up the signed-in customer's own orders by a
   **verified** email (sign-up does not verify emails). Is it wanted?
3. Only the customer's first name is sent to OpenAI now (it used to be the full name). Is that enough for the
   greeting?
4. Customers' conversations live at OpenAI and here. Is there a retention or "delete my data" requirement?
5. Log-in attempts are not rate limited in the app.
6. Which of the two repos is the real one?
