---
name: "nta-product-resolver"
version: "1.0"
description: "Canonical NTA resolver for exact Shopify product and variant identity, supplier mappings, and duplicate prevention."
---

# NTA Product Resolver

## Purpose

Resolve the exact Shopify product and variant before a product decision, inventory action, order action, or Shopify write. This module is the canonical interface; `nta-product-identity-resolver` remains a compatibility alias and must not diverge.

## Contract

Use the match priority, duplicate prevention, review triggers, and output schema in `nta-product-identity-resolver`. Return that `identity` object unchanged, plus the stable `resolution_id` and a `resolution_status` of `RESOLVED`, `REVIEW_REQUIRED`, `UNMATCHED`, or `BLOCKED`.

`RESOLVED` requires a unique exact/high-confidence variant match and acceptable duplicate risk. A fuzzy title candidate is evidence only, never write authority.

## Ownership

This module owns identity only. It does not classify, convert packs, calculate cost, decide price or availability, create content, or mutate Shopify. Call `nta-product-classifier` after resolution where category-aware behaviour is needed.

## Compatibility

Existing callers of `nta-product-identity-resolver` continue to work. New workflows must reference `nta-product-resolver`; the legacy module delegates its rules and output to this contract.
