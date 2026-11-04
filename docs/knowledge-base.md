# The knowledge base

The chatbot can search a **vector store** with OpenAI's `file_search` tool. The store is built once with a command
and referenced by its id. Without one, the chatbot answers from its instructions only.

```bash
uv run lilac-chatbot init-knowledge --shopify              # the shop's active products
uv run lilac-chatbot init-knowledge --file faq.md --file policy.pdf
uv run lilac-chatbot init-knowledge --shopify --file faq.md
```

The command prints `VECTOR_STORE_ID=vs_...`. Put that line in `.env` and restart the app. To change the content,
run the command again and use the new id (the old store is left in your OpenAI account; delete it there).
Uploading stops at the first file OpenAI cannot index; the half-built store is left behind in the same way.

## What the `--shopify` catalogue holds

Title, type, brand, price range, tags, page path, description, and whether the product was in stock at export.
Active products only, all pages (up to 10,000 products). Availability is a snapshot: it can be out of date by the
time a customer asks.

## What is deliberately not in it

The first version loaded every Shopify **customer** and **order** (names, addresses, emails, order history) into the
vector store the chatbot answered from, so any signed-in customer could ask it about other customers. Only products
are read now. The GraphQL query asks for product fields only, and a test fails if the word `customer`, `order`,
`email`, `address` or `phone` appears in it. Draft and archived products are skipped, and the Shopify access token
is sent in a header, never in a URL.

The persona's rule "if the customer is unable to provide the order id, answer this based on the context provided"
used to rely on that order data. The chatbot now knows an order only from what the customer says. Looking up a
customer's own orders needs an authenticated, per-customer lookup (and a verified email, which sign-up does not
check), not a shared index. That is not built (see the questions in `work-done.md`).

## Shopify access

`SHOPIFY_SHOP` must be the shop's `*.myshopify.com` domain (the token is sent to that host, so any other domain is
refused). `SHOPIFY_ACCESS_TOKEN` is an Admin API access token with the `read_products` scope. The API version is
`SHOPIFY_API_VERSION` (default 2026-10). Shopify's GraphQL errors arrive with HTTP 200; they are reported by code
only, never with their text.
