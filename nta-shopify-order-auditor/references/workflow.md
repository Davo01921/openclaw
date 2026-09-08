# nta-shopify-order-auditor workflow

Canonical verification flow:

1. Receive caller-supplied exact order ID and authorised expected state.
2. Confirm a concrete fresh Shopify order-read adapter capability exists.
3. Read the exact order fresh after the write. Do not reuse the writer response as proof.
4. Run `scripts/order_audit.py` against the fresh snapshot.
5. Compare only explicitly expected fields.
6. Return `PASS` only when every expected field matches.
7. Return `FAIL` for material mismatches.
8. Return `REVIEW_REQUIRED` when identity, read capability, expected-state shape, or fresh evidence is insufficient.

This auditor never writes, repairs, fulfils, or adjusts inventory.

Supported comparisons:

- exact order ID;
- exact customer ID;
- exact variant IDs and quantities;
- discount code;
- total amount;
- financial status;
- zero-balance condition;
- tags with explicit SUBSET or EXACT semantics;
- note.

Fulfilment state and inventory effects are intentionally out of scope and belong to separate canonical auditors.
