# NTA automation migration register

This register is based on the current repository tree as at the modular-orchestrator refactor. It excludes financial workflows by design.

| Finding | Previous state | Canonical outcome |
|---|---|---|
| Product resolution naming | `nta-product-identity-resolver` was the only interface | `nta-product-resolver` is canonical; legacy name remains compatible |
| Shopify write verification | Writer and QA auditor were manually paired by callers | `nta-shopify-write-verifier` owns the paired mutation/read-back contract |
| Top-level routing | `nta-product-orchestrator` routed product work only | `nta-automation-orchestrator` routes all non-financial workflows |
| Supplier/inventory logic | Both repeat parts of matching, unit conversion and verification | They delegate to product modules and the write verifier |
| Betta Shopify actions | Specialised workflow had its own discovery/mutation/read-back rules | It retains media-specific behaviour but uses shared resolution and verification contracts |
| Dropship workflow | Referenced by pricing context, absent as a repository skill | Added a safe adapter contract; supplier integration remains a configuration gap |
| Shipping workflow | Referenced operationally, absent as a repository skill | Added a safe fulfilment-event contract; carrier/ShipStation adapter remains a configuration gap |
| Model delegation | Cost/model rules appeared in specialist workflows, product orchestration and a Gemini-specific router | `adaptive-model-router` v2.1 is the sole authority for interchangeable general inference/reasoning model selection; `SOUL.md` makes the rule global even for direct specialist invocation; specialist model wording is capability/eligibility guidance only |
| Specialist generation services | General model routing and fixed provider-specific operations were previously easy to conflate | Fixed, non-substitutable specialist services may remain workflow-owned for their bounded operation; Betta `grok_hero` is explicitly separated from general inference/review routing |
| Provider policy | Router hard-coded Gemini primary/OpenAI fallback and discussed a future Llama route | Retired for general model work; intended policy is OpenAI/ChatGPT primary → Qwen Token Plan fallback → Qwen API backup, with exact model slugs taken from live OpenClaw configuration |

## Remaining implementation gaps

The skills repository intentionally contains instructions/contracts, not live credentials or provider-specific code. The following require configured adapters and end-to-end dry-run evidence before production enablement:

- supplier API/order-submission adapter and acknowledgement normalisation;
- shipping/carrier or ShipStation event adapter;
- durable job/idempotency ledger shared across Discord, Shopify and webhook triggers;
- concrete Shopify operation adapter implementing the write-verifier record;
- automated regression fixtures for supplier packs, preorder transitions, duplicate events, Betta media order, partial Shopify failures, and model-routing/fallback attestation;
- runtime confirmation that OpenClaw's configured general-provider chain matches the intended OpenAI → Qwen Token Plan → Qwen API policy.

No financial workflow was migrated or added.
