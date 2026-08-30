# David's OpenClaw Skills

This private repository is the source of truth for David's custom OpenClaw skills.

## NTA product system

Use `nta-product-orchestrator` as the top-level router for product work. It delegates to canonical modules rather than duplicating domain rules.

Core product modules:

- `nta-product-orchestrator`
- `nta-product-identity-resolver`
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
- `nta-shopify-product-writer`
- `nta-product-qa-auditor`

Specialist product workflows that sit on top of the modular system:

- `nta-supplier-order-processing`
- `nta-inventory-update`
- `nta-betta-picture-processing-v2` (exposes `betta-picture-processing`)
- `nta-individual-betta-shopify-update`

Core architecture rule:

**Skills decide. Writers write. Auditors verify.**

Physical inventory and customer availability/preorder state are separate concerns. Product-domain rules should have one canonical source of truth and should be referenced by specialist workflows rather than copied into them.

## Other active skills

- `adaptive-model-router`
- `nta-death-loss-order`
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
