# David's OpenClaw Skills

This private repository is the source of truth for David's custom OpenClaw skills.

## Operating principles

Before reasoning about or executing work from this repository, consult [`SOUL.md`](SOUL.md). It defines the default decision style, challenge standard, evidence discipline, communication approach, and operating philosophy for David's OpenClaw/Codex workflows. Skills provide task-specific rules; `SOUL.md` provides the behavioural layer above them.

## NTA automation system

Use `nta-automation-orchestrator` as the top-level router for all non-financial NTA automation. Product work enters `nta-product-orchestrator`; specialist workflows retain their own intake and external-system semantics, but consume shared modules rather than copy product or Shopify rules.

Financial, debt, repayment, banking, and accounting workflows are deliberately outside this repository architecture.

### Control plane

- `nta-automation-orchestrator` — selects the workflow, establishes the job envelope and completion contract.
- `adaptive-model-router` — selects a configured execution route; models never receive authority merely because they are expensive.
- `nta-product-orchestrator` — coordinates product-domain modules.

### Canonical shared modules

- `nta-product-resolver` — canonical exact product/variant resolution and duplicate prevention.
- `nta-product-identity-resolver` — compatibility entry point for the resolver.
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
- `nta-dymo-tank-label` — read-only deterministic two-line DYMO livestock tank-label formatter; Shopify `custom.arrival_date` is its only arrival-date source.

Specialist product workflows that sit on top of the modular system:

- `nta-supplier-order-processing`
- `nta-inventory-update`
- `nta-betta-picture-processing-v2` (exposes `betta-picture-processing`)
- `nta-individual-betta-shopify-update`
- `nta-dropship-order-processing`
  - supplier adapter: `nta-dropship-supplier-aqua-premium`
- `nta-shipping-fulfilment`

Core architecture rule:

**Skills decide. Writers write. Auditors verify.**

Physical inventory and customer availability/preorder state are separate concerns. Product-domain rules should have one canonical source of truth and should be referenced by specialist workflows rather than copied into them.

See [ARCHITECTURE.md](ARCHITECTURE.md) for routing, ownership and model-cost rules, and [GAPS_AND_DUPLICATES.md](GAPS_AND_DUPLICATES.md) for the current migration register.

## Other active skills

- `adaptive-model-router`
- `nta-customer-service` — evidence-first customer-service decision engine with responsibility classification, ACL-aware review, proportionate remedies, and anonymised precedent patterns.
- [`nta-death-loss-order`](nta-death-loss-order/) — production death/loss batching; includes [SOP](nta-death-loss-order/SOP.md), [TECHDOC](nta-death-loss-order/TECHDOC.md), and [SPECDOC](nta-death-loss-order/SPECDOC.md).
- `nta-gumtree-listing`

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
