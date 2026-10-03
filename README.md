# David's OpenClaw Skills

This private repository is the source of truth for David's custom OpenClaw skills.

## Operating principles

Before reasoning about or executing work from this repository, consult [`SOUL.md`](SOUL.md). It defines the default decision style, challenge standard, evidence discipline, communication approach, model-routing invariant, and operating philosophy for David's OpenClaw/Codex workflows. Skills provide task-specific rules; `SOUL.md` provides the behavioural layer above them.

## NTA automation system

Use `nta-automation-orchestrator` as the top-level router for all non-financial NTA automation. Product work enters `nta-product-orchestrator`; specialist workflows retain their own intake and external-system semantics, but consume shared modules rather than copy product or Shopify rules.

Financial, debt, repayment, banking, and accounting workflows are deliberately outside this repository architecture.

### Control plane

- `nta-automation-orchestrator` — selects the workflow, establishes the job envelope and completion contract.
- `adaptive-model-router` — sole authority for interchangeable reasoning, extraction, review and vision-inference model/provider selection and escalation. It removes deterministic work first, then resolves model-required phases against live OpenClaw configuration. The intended general-provider policy is OpenAI/ChatGPT primary → Qwen Token Plan fallback → Qwen API backup.
- `nta-product-orchestrator` — coordinates product-domain modules.

The general model-routing rule is global. A specialist skill invoked directly still inherits `adaptive-model-router` through `SOUL.md`; specialist wording such as `cheap model`, `vision model`, `reasoning reviewer`, or `stronger model` is capability guidance only and must not create an independent general provider/model policy.

A fixed, non-substitutable specialist service may remain owned by the specialist workflow for its bounded operation. For example, Betta `grok_hero` may remain a fixed Grok/xAI image-generation stage; this does not make Grok an eligible general reasoning/review route.

### Canonical shared modules

- `nta-product-resolver` — canonical exact product/variant resolution and duplicate prevention.
- `nta-product-identity-resolver` — compatibility entry point for the resolver.
- `nta-product-barcode` — preserves existing Shopify variant barcodes; when a DYMO label workflow finds one missing, deterministically creates an internal `NTA-V-<variant-id>` barcode, collision-checks it, writes it through the canonical verifier, and requires fresh Shopify read-back before printing.
- `nta-product-classifier`
- `nta-supplier-unit-cost-normalizer`
- `nta-retail-pricing-standard`
- `nta-product-facts-research`
- `nta-product-description-standard`
- `nta-inventory-state`
- `nta-product-availability`
- `nta-product-merchandising`
- `nta-product-metafields`
- `nta-product-exception-gate`
- `nta-shopify-write-verifier` — canonical write boundary: authorised change set → write → fresh read-back assertion.
- `nta-shopify-product-writer` — write-phase implementation used by the verifier.
- `nta-product-qa-auditor` — verification-phase implementation used by the verifier.
- `nta-dymo-tank-label` — deterministic two-line DYMO livestock tank-label formatter/printer. The label module itself is read-only with respect to Shopify; missing-barcode creation is owned upstream by `nta-product-barcode` and must be verified in Shopify before physical printing.

Specialist product workflows that sit on top of the modular system:

- `nta-supplier-order-processing`
- `nta-inventory-update`
- `nta-betta-picture-processing-v2` (exposes `betta-picture-processing`)
- `nta-individual-betta-shopify-update`
- `nta-dropship-order-processing`
  - supplier adapter: `nta-dropship-supplier-aqua-premium`
- `nta-shipping-fulfilment`

Core architecture rule:

**Skills decide. Writers write. Auditors verify. The adaptive router chooses general model capacity.**

Physical inventory and customer availability/preorder state are separate concerns. Product-domain rules should have one canonical source of truth and should be referenced by specialist workflows rather than copied into them.

`Davo01921/openclaw-skills` is the canonical source of truth. Fred’s `agent-memory/skills` and local `~/.openclaw/workspace/fred/skills` copies are deployment mirrors only and must not override canonical skill behavior.

See [ARCHITECTURE.md](ARCHITECTURE.md) for routing, ownership and model-cost rules, and [GAPS_AND_DUPLICATES.md](GAPS_AND_DUPLICATES.md) for the current migration register.

## Other active skills

- `adaptive-model-router`
- `nta-customer-service` — evidence-first customer-service decision engine with responsibility classification, ACL-aware review, proportionate remedies, and anonymised precedent patterns.
- [`nta-death-loss-order`](nta-death-loss-order/) — v1.4.1 production death/loss batching, **CLOSED / PRODUCTION / BAU** after successful genuine scheduled acceptance on 3 October 2026; includes [SOP](nta-death-loss-order/SOP.md), [TECHDOC](nta-death-loss-order/TECHDOC.md), and [SPECDOC](nta-death-loss-order/SPECDOC.md).
- [`nta-gumtree-listing`](nta-gumtree-listing/README.md) — CLOSED / BAU; deterministic manual-post engine, with catalogue decisions handled in operations.

## Safety

Live credentials, `.env` files, machine-specific configuration, business exports,
memory, and customer data must not be committed. Use example configuration files
for documented settings.

## Workflow

1. Modify and test a skill in this directory.
2. Review `git diff` and scan for secrets.
3. Commit the change with a descriptive message.
4. Push to GitHub.

The retired local `betta-picture-processing/` duplicate is intentionally ignored;
`nta-betta-picture-processing-v2/` is canonical.

Shipping Fulfilment V2: [CLOSED / BAU](nta-shipping-fulfilment/docs/CLOSEOUT.md). PR #17 closes the tracking, handoff and durable-idempotency gaps; the live replay is optional BAU confidence testing.

Betta Processing: [one canonical V2.1 workflow, final acceptance pending](nta-betta-picture-processing-v2/docs/CLOSEOUT.md). Experimental V3 is deferred.

Catalogue Integrity: [finite audit complete; physical/shipping facts blocked](nta-inventory-state/docs/CLOSEOUT.md). No guessed stock changes.

[Medium-priority closeout status](STATUS.md) and [executive evidence/acceptance record](docs/NTA_MEDIUM_PRIORITY_CLOSEOUT_2026-10-02.md).
