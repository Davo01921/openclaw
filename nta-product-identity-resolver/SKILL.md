---
name: "nta-product-identity-resolver"
version: "1.1"
description: "Compatibility entry point for the canonical nta-product-resolver identity, supplier mapping, SKU, and duplicate-risk contract."
---

# NTA Product Identity Resolver — v1.1

## Compatibility status

`nta-product-resolver` is the canonical module for new workflows. This skill remains available for existing callers and uses the same match priority, output contract, duplicate prevention, and review gates. Do not add independent rules here; update the canonical resolver contract instead.

## Purpose

Establish exactly which Shopify product/variant a product job refers to before any downstream decision or write.

This skill owns identity resolution only. It does not decide retail price, inventory quantity, preorder status, description content, tags, collections, or metafield values.

## Match priority

Use the strongest available identifiers in this order:

1. exact Shopify variant ID/product ID supplied by trusted workflow;
2. exact SKU;
3. exact barcode;
4. exact supplier SKU mapped to known Shopify SKU/variant;
5. exact product + variant match;
6. high-confidence normalized title/vendor match;
7. fuzzy title similarity only as a candidate, never as silent authority.

## Required output

Return:

```yaml
identity:
  title:
  shopify_product_id:
  shopify_variant_id:
  sku:
  barcode:
  vendor:
  supplier_sku:
  match_method:
  match_confidence: HIGH | MEDIUM | LOW
  duplicate_risk: NONE | POSSIBLE | HIGH
  creation_candidate: true | false
  notes: []
```

## Rules

- Read live Shopify before concluding an existing product is absent.
- Match the exact variant, not only the parent product, where variants exist.
- Preserve the distinction between supplier ordering units and Shopify selling units; identity resolution does not perform pack arithmetic.
- Never create a new product simply because a supplier line did not match immediately.
- If multiple plausible matches exist, return `LOW` confidence and require review.
- Existing title text is weaker evidence than SKU/barcode/supplier code.
- A spelling difference or abbreviated supplier name does not automatically mean a new product.
- A size, sex, colour, pack quantity, model number, or form difference may indicate a distinct variant/product and must not be collapsed without evidence.

## Duplicate prevention

Before recommending creation, search for:

- same SKU/barcode;
- title synonyms;
- old/archived products;
- alternate vendor naming;
- singular/plural variants;
- scientific/common-name equivalents for livestock/plants;
- model-number equivalents for dry goods.

Creation may proceed only when duplicate risk is acceptably low and the calling workflow has creation authority.

## Human-review triggers

Return review when:

- two Shopify variants share plausible identifiers;
- supplier SKU appears reused ambiguously;
- a supplier line is assorted and maps to several products;
- title and SKU evidence conflict;
- pack/size wording could represent either a variant or a supplier pack;
- a one-off livestock item appears similar to an existing commodity product but may be individually identified.
