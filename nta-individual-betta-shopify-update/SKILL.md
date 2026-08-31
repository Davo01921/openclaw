---
name: "nta-individual-betta-shopify-update"
description: "Retire the old Shopify-only Betta skill and redirect legacy invocations to the unified Betta workflow."
---

# Retired workflow

Do not execute this workflow independently.

Use the live `betta-picture-processing` skill for all NTA individual-Betta work, including Discord intake, CSV creation, hero/reference image processing, Shopify product updates, inventory and arrival-date verification, archival, and final reporting. The unified workflow uses `nta-product-resolver` and `nta-shopify-write-verifier` for shared Shopify safety.

If explicitly invoked by this retired skill name, immediately route the request to `betta-picture-processing` and follow its current instructions. Do not run a second pass or duplicate Shopify writes.
