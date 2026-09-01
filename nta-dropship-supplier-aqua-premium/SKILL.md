---
name: "nta-dropship-supplier-aqua-premium"
version: "1.0"
description: "Supplier adapter for NTA Aqua Premium dropship hand-offs and acknowledgement matching without inventing unsupported supplier APIs."
---

# NTA Dropship Supplier — Aqua Premium

## Purpose

Translate the canonical NTA dropship supplier request into an Aqua Premium hand-off, capture evidence of submission, and match Aqua Premium's acknowledgement/order number back to the originating Shopify order.

This adapter is supplier-specific. It does not decide whether a Shopify line is eligible for dropship; eligibility is owned by `nta-dropship-order-processing`.

## Known supplier channels

Verified from NTA's existing Aqua Premium correspondence:

- Sales: `sales@aquapremium.com.au`
- General/sales contact seen historically: `chris@aquapremium.com.au`
- Dispatch correspondence: `dispatch@aquapremium.com.au`
- Aqua Premium invoices historically contain numeric invoice/order references such as `00023943`.

Use `sales@aquapremium.com.au` as the default order-submission destination unless a newer explicitly configured Aqua Premium ordering address or API supersedes it. Do not send an order to dispatch unless the configured business process explicitly requires it.

## Transport priority

1. A deliberately configured and verified Aqua Premium API/EDI adapter, if one exists.
2. Email hand-off through NTA's authorised mailbox.
3. Manual Aqua Premium portal entry with captured evidence.

Never invent an Aqua Premium API endpoint, token, portal automation, acceptance response, or ordering address.

## Input contract

Accept `supplier_request` from `nta-dropship-order-processing`:

```yaml
supplier_request:
  supplier: Aqua Premium
  shopify_order_id:
  shopify_order_name:
  idempotency_key:
  ship_to:
    name:
    company:
    address1:
    address2:
    city:
    province:
    postcode:
    country:
    phone:
  lines:
    - shopify_line_item_id:
      shopify_product_id:
      shopify_variant_id:
      supplier_sku:
      title:
      variant_title:
      quantity:
  notes:
```

Reject any request whose supplier is not exactly `Aqua Premium`.

## Email hand-off

### Recipient

Default: `sales@aquapremium.com.au`

### Subject

`NTA DROPSHIP — Shopify <shopify_order_name> — <idempotency short token>`

The Shopify order name must always be present in the subject and body so incoming supplier correspondence can be matched deterministically.

### Body fields

Include only information required for Aqua Premium to fulfil the order:

- NTA Shopify order name
- explicit statement: `Please dropship directly to the customer below.`
- product line(s): supplier SKU when known, product title, variant, quantity
- delivery name and address
- customer phone only when needed for carrier delivery
- instruction that Aqua Premium should reply with its order/invoice/reference number
- idempotency token

Do not include product retail prices, unrelated Shopify lines, customer email, order payment information, or unrelated customer history unless explicitly required for fulfilment.

### Required acknowledgement instruction

Every outgoing request must ask Aqua Premium to include the NTA Shopify order name in the reply and provide their order/invoice/reference number.

## Submission evidence

A hand-off is `SENT` only when there is durable evidence of submission, for example:

- Gmail sent-message ID + timestamp + recipient + subject; or
- verified API acknowledgement ID; or
- manual portal confirmation/reference captured by the operator.

Store the evidence against the dropship idempotency key. An SMTP/API timeout without a sent-message record is `AMBIGUOUS`, not permission to resend.

## Acknowledgement matching

When new Aqua Premium correspondence is inspected, match in this order:

1. Exact Shopify order name in subject/body.
2. Exact idempotency token.
3. Reply/thread relationship to the original supplier request.
4. Product/customer/address correlation only as supporting evidence, never as the sole match when more than one candidate exists.

Expected Aqua Premium sender domains/addresses include `@aquapremium.com.au`, with historical correspondence from sales, dispatch, accounts and staff addresses.

Extract a supplier reference only when it is explicitly presented as an Aqua Premium order, invoice, sales order, dispatch or equivalent reference. Do not guess a reference from tracking numbers, phone numbers, monetary amounts, dates or attachment filenames unless the filename clearly encodes the supplier invoice/order reference and the message context confirms it.

If more than one plausible reference exists, return `REVIEW_REQUIRED`.

## Return contract

```yaml
supplier_result:
  supplier: Aqua Premium
  shopify_order_id:
  shopify_order_name:
  idempotency_key:
  transport: email | api | manual_portal
  submission_state: SENT | AMBIGUOUS | FAILED | NOT_SENT
  submission_evidence:
    message_id:
    timestamp:
    recipient:
    subject:
  acknowledgement_state: NONE | MATCHED | REVIEW_REQUIRED
  supplier_order_number:
  acknowledgement_evidence:
    message_id:
    sender:
    subject:
    timestamp:
  warnings: []
```

## Shopify callback

This adapter does not write directly to Shopify. Return the supplier result to `nta-dropship-order-processing`, which must pass authorised order changes through `nta-shopify-write-verifier`.

When `supplier_order_number` is confidently matched, the parent workflow should set:

- `custom.supplier_order_number = <reference>`
- `custom.dropship_status = SUPPLIER_ACKNOWLEDGED`

and add a non-destructive human-readable order note/comment equivalent where supported.

## Idempotency and retries

- One supplier submission per idempotency key unless a prior attempt is conclusively `FAILED` or an authorised human approves a retry.
- `AMBIGUOUS` submissions must be investigated before retrying.
- A supplier acknowledgement proves receipt but does not prove customer fulfilment.
- Never mark a Shopify order fulfilled from this adapter.
