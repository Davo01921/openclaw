# nta-customer-service

Customer-service decision support for Nano Tanks Australia.

## Purpose

This skill turns a complaint or service request into a consistent decision rather than an improvised reply. It is designed for cases involving livestock, refunds, replacements, shipping, product representations, pickup issues, fulfilment mistakes, and goodwill requests.

The core sequence is:

**facts → responsibility → policy/ACL → evidence gaps → devil's-advocate test → proportionate remedy → confidence → customer response**

## Files

- `SKILL.md` — operational instructions used by OpenClaw.
- `DECISION_ENGINE.md` — detailed reasoning framework.
- `CASE_EXAMPLES.md` — anonymised examples and precedent patterns.

## Key principle

The skill does not automatically defend NTA and does not automatically concede to the customer. It is intended to produce a decision that remains reasonable when tested against the evidence, the customer's strongest argument, NTA policy, and applicable Australian Consumer Law.

## Data safety

Do not commit live customer records or identifiers to this directory. Shopify, messages, photos, videos, and other customer evidence should be reviewed at runtime and referenced only in the active case. GitHub examples must remain anonymised.
