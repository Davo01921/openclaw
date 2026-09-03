# NTA Dropship Order Processing — Acceptance Tests

These tests define the minimum behaviour required before automatic Shopify triggering is enabled.

## T01 — No dropship lines

Given an order containing only products where `custom.dropship != true`, return `NO_ELIGIBLE_LINES`. Do not tag the order, write dropship status, contact a supplier, or alter fulfilment.

## T02 — One Aqua Premium dropship line

Given one line whose live product state has:

- `custom.dropship = true`
- `custom.dropship_supplier = Aqua Premium`

build exactly one Aqua Premium supplier group, include the exact Shopify order and line identifiers, set `READY_FOR_HANDOFF`, add `NTA-DROPSHIP-AQUA-PREMIUM`, then dispatch through `nta-dropship-supplier-aqua-premium`.

## T03 — Mixed normal and dropship order

Given a Shopify order with both normal NTA lines and Aqua Premium dropship lines, send only qualifying dropship lines to Aqua Premium. Never include unrelated lines in the supplier request.

## T04 — Multiple Aqua Premium lines

Given several qualifying Aqua Premium lines in one Shopify order, create one grouped supplier request rather than one request per line.

## T05 — Variant fidelity

Given a multi-variant product, the payload must preserve the exact Shopify variant ID, variant title and quantity. If a supplier SKU exists, include it. Never substitute a sibling variant.

## T06 — Missing supplier SKU

A missing supplier SKU alone must not silently invent one. Include Shopify identity data and warning `SUPPLIER_SKU_MISSING`. If title/variant identity is otherwise exact, the hand-off may proceed according to configured review policy; ambiguous identity must return `REVIEW_REQUIRED`.

## T07 — Duplicate trigger

Given the same Shopify order event more than once, compute the same idempotency key. If a successful supplier hand-off already exists for that key, do not resend.

## T08 — Ambiguous email send

If email transport reports an ambiguous failure and no durable sent-message evidence is available, return `AMBIGUOUS`. Do not retry automatically.

## T09 — Supplier acknowledgement

Given an Aqua Premium reply that contains the exact Shopify order name and a clear Aqua Premium order/invoice/reference number, return `MATCHED`, write that reference to `custom.supplier_order_number`, and set `custom.dropship_status = SUPPLIER_ACKNOWLEDGED` through `nta-shopify-write-verifier`.

## T10 — Conflicting supplier reference

If Shopify already contains a different non-empty `custom.supplier_order_number`, do not overwrite it. Return `REVIEW_REQUIRED`.

## T11 — Tracking number is not order number

If an Aqua Premium dispatch email contains only a carrier tracking number, do not write it into `custom.supplier_order_number` unless the message explicitly identifies the same value as Aqua Premium's order/invoice/reference number.

## T12 — Fulfilment isolation

At no point may supplier submission or acknowledgement mark the Shopify order fulfilled. Fulfilment remains owned by `nta-shipping-fulfilment`.

## T13 — Customer data minimisation

The supplier payload may contain delivery name/address and phone when needed for carrier delivery. It must not contain unrelated customer history, payment information, unrelated order lines, or customer email unless explicitly required by the configured supplier process.

## T14 — Supplier route is metafield-driven

Vendor/brand alone must never trigger or choose a supplier. The workflow must read the live `custom.dropship` and `custom.dropship_supplier` product metafields.

## T15 — Aqua Premium email format

For email transport, subject must include the Shopify order name and an idempotency token. Body must ask Aqua Premium to reply with its order/invoice/reference number and preserve the Shopify order name in the reply.

## Go-live gate

Automatic Shopify order triggering is permitted only when T01–T15 pass in dry-run/test orders and a real event receiver or scheduled runner is configured. A skill definition alone is not a webhook endpoint.
