# Gumtree engine closeout — 2 October 2026

**Final status: CLOSED / BAU.** Initial classification A: implementation complete; deployment instructions, current operations and closure documentation needed reconciliation.

Purpose: safely prepare and track NTA advertisements from current Shopify facts without duplicate listings or invented availability. Final architecture is Shopify read → configuration/availability → SQLite identity → deterministic reconciliation/listing plan → bounded Sydney-date operator queue → manual account action → explicit verification. PRs #4–#16 are merged; PR #16 (`b33e71e`) established the production manual-post contract. No browser publisher is a production dependency.

## Evidence

- Canonical source at `c8c5b83`: `python3 -m pytest nta-gumtree-listing/tests -q` — **174 passed** on 2 October. Coverage includes management gates, duplicate IDs, stock-zero outcomes, update/pause/remove review paths, idempotency, backup, migration, manual bootstrap and post/verification lifecycle.
- Live registry `/Users/davidlo/openclaw-skills-v3/nta-gumtree-listing/data/gumtree.db`: SQLite integrity **ok**, five products, five mappings, three recorded listing instances. Transactionally consistent backup independently returned integrity **ok**.
- Fresh Shopify Admin read of all five registered products: Blackworms 0, Red Cherry Shrimp 0, White Caridina 84, Scarlet Blue Endler 13, Pea Puffer 18. None currently has a Gumtree activation policy. Cached CONFIGURED state is not current authority.
- Production queue code against those live facts and a backup registry: Sydney date **2026-10-02**, allowed day true, **zero items**, five skipped, zero snapshot errors; publish/browser authority false. This is the correct fail-closed result.
- Replaced the obsolete main-agent workshop browser instructions with the canonical manual-post skill and corrected six existing scheduled product reminders. Their schedule/product identity was preserved; no task was triggered and no marketplace action occurred.
- Private evidence and runtime rollback copies are under `/Users/davidlo/MediumProjectClose02102026/evidence/`; database/queue exports remain outside Git.

## Catalogue operations

| Listing | Current operational classification | Action |
|---|---|---|
| Blackworms, 1344082320 | NEEDS HUMAN REVIEW | Recorded NEEDS_REVIEW; quantity 0, no live policy. Confirm genuinely available supply before choosing an always-on exception; otherwise manually pause/archive. |
| Red Cherry, 1344082647 | ARCHIVE | Quantity 0, recorded NEEDS_REVIEW. Operator must confirm current listing and manually pause/archive; no automatic removal. |
| White Caridina | HOLD | Stock 84; mapped, no recorded listing and no activation policy. Configure only after a business decision. |
| Scarlet Blue Endler | HOLD | Stock 13; mapped, no recorded listing and no activation policy. Configure only after a business decision. |
| Pea Puffer, 1344618543 | ACTIVE (registry record) | Stock 18. Existing manual listing reference is retained; current Gumtree account state needs operator observation, not scraping. Missing policy prevents a new package. |
| Held Betta conflict | HOLD | No corresponding registered identity among the five products. Require an exact existing listing/product decision before adding a mapping. |

These six decisions do not require further engine development. No ads, customer communications or paid promotions were sent.

BAU owner: David handles listing/content decisions and manual account operations; automation prepares packages and preserves evidence. Limitations: manual observation is required for live account state; registry facts can be stale; unconfigured products never activate implicitly. Recovery and logs are in [SOP](../SOP.md); enhancements are in [future backlog](../FUTURE_BACKLOG.md).
