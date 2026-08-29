# David's OpenClaw Skills

This private repository is the source of truth for David's custom OpenClaw skills.

## Active skills

- `adaptive-model-router`
- `nta-betta-picture-processing-v2` (exposes `betta-picture-processing`)
- `nta-death-loss-order`
- `nta-gumtree-listing`
- `nta-individual-betta-shopify-update`
- `nta-inventory-update`

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
