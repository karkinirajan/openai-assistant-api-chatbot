# Replacement requests

The persona (the original system prompt) walks a customer with a faulty product through a fixed conversation and
ends with the assistant saying it has arranged a replacement that "will ship tomorrow" (or Monday, after Friday
and Saturday), with an order confirmation by email, "noted in your original order as a 100% discount with free
shipping". The brief behind it asks for such orders to be tagged so they can be counted monthly or yearly.

**Nothing in this project creates that order.** The first version asked the model for a JSON flag, `is_order`, and
never used it.

## What happens now

* The model is asked for a structured reply: `is_order` (true when the customer asks for a replacement or an order
  and has given an order id and a product), `order_id` (empty when there is none) and `answer`.
* The customer sees `answer` only. The flag and the order id are saved with the assistant's message.
* A reply that is valid JSON of another shape, or not JSON at all, is shown as plain text with the flag off. The
  flag is read strictly: the text `"yes"` or the number `1` does not count as true.
* `uv run lilac-chatbot replacements` lists the flagged replies (time, username, order id, the start of the reply)
  and ends with a count by month.

## What it is not

It is a work list for a person, not a fulfilment system. Whether a flagged request is genuine, whether the order id
exists, and what to send are decisions the shop still has to make. The model can flag a request wrongly or miss
one, and the list says nothing about requests the model did not flag.
