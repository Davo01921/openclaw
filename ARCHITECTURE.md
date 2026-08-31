# NTA automation architecture

## Target shape

```text
nta-automation-orchestrator
├─ adaptive-model-router                 (execution route only)
├─ nta-product-orchestrator              (product decisions)
│  ├─ nta-product-resolver               (exact product/variant identity)
│  ├─ domain modules                     (classification, cost, price, facts, description,
│  │                                      inventory, availability, merchandising, metafields)
│  ├─ nta-product-exception-gate         (write authority)
│  └─ nta-shopify-write-verifier         (write + fresh read-back)
│     ├─ nta-shopify-product-writer
│     └─ nta-product-qa-auditor
└─ specialist workflows                  (source-specific intake and idempotency)
   ├─ supplier order / inventory update
   ├─ Betta batch and individual Betta compatibility entry point
   ├─ dropship order
   ├─ shipping fulfilment
   └─ death/loss order
```

## Ownership

| Concern | Canonical owner | Must not be duplicated by |
|---|---|---|
| Product/variant identity and duplicate risk | `nta-product-resolver` | supplier, inventory, Betta, dropship |
| Product classification | `nta-product-classifier` | pricing, description, availability |
| Cost/unit conversion | `nta-supplier-unit-cost-normalizer` | supplier and inventory intake |
| Retail decision | `nta-retail-pricing-standard` | intake workflows |
| Description and content QA | `nta-product-description-standard` | Betta and catalogue workflows |
| Physical stock | `nta-inventory-state` | availability and shipping |
| Customer availability/preorder | `nta-product-availability` | inventory and supplier parser |
| Shopify write/read-back | `nta-shopify-write-verifier` | every specialist workflow |

## Cost-efficient delegation

Use no model for structured parsing after extraction, arithmetic, state changes, payload construction, idempotency checks, Shopify calls, and assertions. Use the cheapest configured capable model for clean extraction, routine classification and non-destructive visual comparison. Escalate through `adaptive-model-router` only for ambiguity, contradictory evidence, biological/product claims, or exception diagnosis. Models may propose facts; they never expand write authority.

## Operational invariant

Every consequential mutation has one job ID, one idempotency key, an authorised change set, an operation record, and a fresh read-back result. A job is complete only when all intended mutations verify or its partial/review state is explicitly reported.
