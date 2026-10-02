# NTA Catalogue Integrity closeout — 2026-10-02

Status: BLOCKED — finite physical inventory and packed-shipping facts required. Audit engineering is complete; stock and shipping defects are not declared fixed.

## Purpose and finite scope
Prevent unsafe oversell, incorrect physical stock, wrong shipment classification and broken operational identity. Cosmetic SEO/image perfection is BAU. This project uses Shopify's existing product/variant inventory model and ShipWeave; no new catalogue system is introduced.

## Current production evidence
Read-only complete export: 2,279 products / 2,739 variants, 2,544 active variants. All exported inventory-level connections are complete. Policies: 2,583 DENY / 156 CONTINUE across the full catalogue. No unapproved CONTINUE retail policy remained after considering exact variant names, product tags, livestock, all plant categories and nonphysical/untracked exceptions. The suspected Easy-Life Blue Exit variant explicitly says 1L - Preorder; two Bio-Exit products carry Preorder tags. No policy or quantity was changed.

132 active variants have a negative on_hand balance. The finite audit identifies **41 tracked, non-preorder physical balances** requiring count/order-ledger reconciliation, and **91 preorder or untracked/nonphysical exceptions** for BAU accounting review. They must not all be reset to zero. Full raw catalogue has 143 negative aggregate balances including inactive records.

**29 shipped variants advertise a net weight above 5 kg but have zero recorded weight**, with a dry classification in the reviewed ShipWeave snapshot. Examples include both NLS Koi 8 kg products, Aqua-Pics 8–20 kg salts/buffers and Aqua Natural 7/9/14 kg substrate variants. Net weight is a lower bound, not packed shipment weight. These need measured packed weight and current ShipWeave heavy/destination verification before changing checkout; no rate or packed weight is invented.

Important review queue: 56 active zero-stock tank-labelled Bettas, 9 duplicate nonempty SKU groups and 17 duplicate nonempty barcode groups among active variants. A shared code can represent supplier variants or pickup/shipped options; do not merge products or replace supplier codes by guesswork. Zero-stock DENY Bettas cannot oversell; verify actual sold/current fish identity before separately authorized archival.

## Repeatable audit and tests
scripts/catalogue_audit.py consumes a complete fresh private export, optionally with reviewed classification rules, and writes only a private report. Seven regression fixtures cover plant/livestock exclusion, fertilizer distinction, explicit variant/tag preorder exceptions, truncated/duplicate snapshots, zero-stock review and heavy-weight detection. Existing inventory-state dry-run remains the canonical quantity/state validation boundary.

Run from repository root:

```sh
python3 -B -m unittest discover -s nta-inventory-state/tests -v
python3 -B nta-inventory-state/scripts/catalogue_audit.py /private/current-catalogue.json --shipping-rules /private/current-rules.json --output /private/catalogue-audit.json
```

## Exact remaining actions
The central evidence/CATALOGUE_ACTIONS.csv contains the 70 exact variant-level blocking findings: reconcile 41 physical balances against a count and committed/open orders, and measure/verify packed shipping for 29 heavy variants. Obtain supplier/operator identity facts before repairing the small duplicate-code groups. Perform changes through the canonical verifier with pre-write baseline, exact IDs, explicit intended values and independent readback. Re-run the audit and require zero unresolved blocking findings before closing.

## BAU, limitations and recovery
Weekly audit after supplier/catalogue batches; operator owns physical counts and classification review. Missing SKUs/barcodes only block a documented operating requirement; do not invent GTINs for internal NTA barcodes. Shipping mapping supplied here is the reviewed 1 October snapshot, not a live ShipWeave read. Cosmetics, SEO and broad photography are FUTURE_BACKLOG.md.

No production inventory, product status or shipping rule was mutated during closeout. Retain private exports/reports and existing inventory audit logs. For later writes, record reversible policy/classification baselines; never blindly restore stock because orders may have changed it. Resolve uncertain mutation outcomes by fresh exact reads before retrying.
