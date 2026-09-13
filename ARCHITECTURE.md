# NTA automation architecture

## Target shape

```text
nta-automation-orchestrator
├─ adaptive-model-router                 (general inference/reasoning model selection)
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

`SOUL.md` makes the `adaptive-model-router` contract global, so specialist workflows invoked directly inherit the same general model-routing rule even when the top-level orchestrator is bypassed.

## Ownership

| Concern | Canonical owner | Must not be duplicated by |
|---|---|---|
| Interchangeable reasoning/extraction/review/vision-inference model selection and escalation | `adaptive-model-router` | every product module and specialist workflow |
| Product/variant identity and duplicate risk | `nta-product-resolver` | supplier, inventory, Betta, dropship |
| Product classification | `nta-product-classifier` | pricing, description, availability |
| Cost/unit conversion | `nta-supplier-unit-cost-normalizer` | supplier and inventory intake |
| Retail decision | `nta-retail-pricing-standard` | intake workflows |
| Description and content QA | `nta-product-description-standard` | Betta and catalogue workflows |
| Physical stock | `nta-inventory-state` | availability and shipping |
| Customer availability/preorder | `nta-product-availability` | inventory and supplier parser |
| DYMO tank-label rendering | `nta-dymo-tank-label` | inventory intake and product orchestrator |
| Shopify write/read-back | `nta-shopify-write-verifier` | every specialist workflow |

## Model routing

General model routing is a control-plane concern, not a domain-skill concern.

1. Remove deterministic work first. Structured parsing after extraction, arithmetic, state changes, payload construction, idempotency checks, Shopify calls, exact comparisons and read-back assertions should use no model when deterministic execution is sufficient.
2. A domain or specialist skill may declare capability needs such as vision, structured extraction, ordinary reasoning or deep review.
3. `adaptive-model-router` alone resolves `NONE`, `LIGHT`, `STANDARD`, `DEEP` or `CRITICAL_REVIEW` for interchangeable general inference/reasoning work and maps that requirement onto live OpenClaw configuration.
4. The intended general-provider policy is OpenAI/ChatGPT primary → Qwen Token Plan fallback → Qwen API backup. Exact model slugs remain runtime configuration, not repository constants.
5. Requested routing and actual execution are separate facts. Provider/model claims require execution metadata.
6. A model route never grants mutation authority; writers, exception gates and explicit authorisation rules remain unchanged.

A fixed, non-substitutable specialist generation/service dependency may remain owned by its specialist workflow for that bounded operation. Example: Betta `grok_hero` may remain a fixed Grok/xAI image-generation stage; Grok is not thereby an eligible general reasoning/review route. If such a service later becomes interchangeable, provider selection should move under `adaptive-model-router` or a dedicated service router.

Specialist wording such as `cheap model`, `vision model`, `reasoning reviewer`, or `stronger model` is only a capability/cost hint and cannot override the canonical router.

## Operational invariant

Every consequential mutation has one job ID, one idempotency key, an authorised change set, an operation record, and a fresh read-back result. A job is complete only when all intended mutations verify or its partial/review state is explicitly reported.
