# NTA Dropship Order Trigger — Acceptance Tests

The trigger passes only when all cases below preserve the downstream idempotency and safety rules.

1. **No dropship lines** — recent paid order contains only products with `custom.dropship=false`; skip as `no_dropship_lines`.
2. **One Aqua Premium line** — paid order created after `activation_at` contains one current unfulfilled line with `custom.dropship=true`; dispatch exact Shopify order identity once.
3. **Mixed order** — one dropship line plus normal NTA stock; dispatch order to processor but never treat normal lines as supplier lines.
4. **Cancelled order** — skip even when product metafields say dropship.
5. **Unpaid order** — default production policy does not supplier-submit; candidate remains blocked/reviewable unless explicit policy overrides payment gate.
6. **Already sent** — `custom.dropship_status=SENT_TO_SUPPLIER` plus durable matching hand-off evidence; do not cause another external submission.
7. **Acknowledged** — `custom.dropship_status=SUPPLIER_ACKNOWLEDGED`; skip supplier submission.
8. **Duplicate poll overlap** — same order appears in consecutive scans because of 10-minute overlap; no duplicate supplier submission.
9. **Duplicate webhook** — same order-created event delivered twice; downstream idempotency prevents duplicate supplier order.
10. **Webhook stale payload** — payload says normal product but live metafield is now dropship=true; live read wins.
11. **Webhook stale payload inverse** — payload says dropship but live metafield is false; live read wins and order is skipped.
12. **Missing product relation** — deleted/custom line cannot resolve live product; `REVIEW_REQUIRED`, never infer from vendor.
13. **Partial GraphQL/page read** — not all line items/metafields fetched; `REVIEW_REQUIRED`, no hand-off.
14. **Shopify read outage** — `BLOCKED`, checkpoint retained.
15. **Processor ambiguity** — processor returns ambiguous supplier transport state; checkpoint/audit retains order for investigation and does not authorize resend.
16. **Zero unfulfilled quantity** — dropship line fully fulfilled/refunded; skip that line.
17. **Multiple suppliers** — trigger dispatches once to order processor; processor owns supplier grouping.
18. **Checkpoint recovery** — process crashes before checkpoint commit; overlapping next scan rediscovering order remains safe due to downstream idempotency.
19. **Order edited after send** — qualifying line set differs after successful hand-off; do not silently create a second supplier order; require processor review for changed line composition.
20. **Manual recovery** — operator supplies exact Shopify order ID/name; same safety and idempotency rules apply as poll/webhook mode.
21. **Historical qualifying order** — paid order has a valid Aqua Premium dropship line but `createdAt < activation_at`; return `HISTORICAL_REVIEW_REQUIRED`, never auto-submit.
22. **Historical order with blank Shopify hand-off metadata** — blank `dropship_status` and `supplier_order_number` do not prove the supplier was never contacted; historical boundary still blocks auto-submit.
23. **Activation boundary equality** — an order with `createdAt == activation_at` may enter normal automatic processing if every other gate passes.
24. **Activation timestamp changed backwards** — moving `activation_at` earlier must not authorize resending historical orders already encountered; require explicit manual recovery evidence.
25. **Real dry-run regression — order #17154 shape** — a partially fulfilled historical order contains multiple dropship-labelled lines, but only one has `unfulfilledQuantity > 0`; only that line may be considered, and because the order predates activation it remains `HISTORICAL_REVIEW_REQUIRED`.
