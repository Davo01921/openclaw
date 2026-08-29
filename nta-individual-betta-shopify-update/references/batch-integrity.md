# Batch integrity and handle safety

Read this reference for multi-product work, handle repairs, or any identity/collision anomaly.

## Ledger

Maintain one row per fish with:

- tank ID
- Product ID
- original title
- original handle
- intended handle
- supplied-image identity confirmed
- arrival date
- intended inventory
- write result
- all Shopify `userErrors`
- read-back result
- final state: PASS, FIX REQUIRED, or BLOCKED

Only PASS counts as complete. Isolate failures and fix only affected records; do not blindly replay successful writes.

## Handle preflight

Build the desired tank → handle map before mutations. Query every desired handle to determine current ownership. Detect duplicate targets, occupied handles, swaps, and longer cycles before writing. Never repurpose an occupied handle without identifying its current Product ID/title/tank.

The Product ID is the stable system identifier. The physical tank label and actual fish are the primary human-verifiable identifiers. Never use handle alone as identity.

## Safe swap

For a two-product handle swap:

1. Move Product A to a verified unique temporary handle such as `4bt25-temp-fix`.
2. Move Product B to its correct final handle.
3. Move Product A to its correct final handle.
4. Avoid unnecessary redirects for temporary internal moves unless explicitly required.
5. After every mutation, inspect `userErrors`.
6. Read both products back and verify Product ID ↔ title/tank ↔ final unique handle.

Use the same temporary-handle principle to break longer cycles.

## Final whole-batch audit

Freshly query every affected Product ID and check:

- unique handle belongs to the correct tank/product;
- Product ID/title/tank/handle/image mapping is intact;
- correct enhanced hero and genuine natural reference are present and ordered;
- images have not shifted to adjacent tanks;
- inventory = 1;
- arrival date is correct;
- title and price are unchanged unless requested;
- status remains expected;
- no unresolved `userErrors`.

Read back every correction again. The batch is DONE only when every ledger row is PASS.
