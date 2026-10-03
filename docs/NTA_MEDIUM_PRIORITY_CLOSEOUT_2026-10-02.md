# NTA medium-priority closeout — 2 October 2026

## Post-closeout update — 3 October 2026

Shipping Fulfilment V2 was owner-accepted as **CLOSED / BAU**. The genuine-dispatch restart/replay exercise described below was waived as a closure blocker and is now an optional BAU confidence check only. The 2 October table and evidence below are retained as the historical closeout snapshot.

**Two projects CLOSED / BAU; four ready for one final genuine acceptance exercise; two have explicit external facts/permission blockers.** No fake production event was created. All completed source changes are committed, pushed and merged after relevant CI. The raw operational evidence is private under /Users/davidlo/MediumProjectClose02102026/evidence.

| Project | Initial classification/status | Work completed | Evidence | Final status | Remaining human action |
|---|---|---|---|---|---|
| StreamShelf | B — reported PiP/download/seek/403 defects | Preserved existing fixes; durable interruption recovery, complete-file validation, seek bounds, exact YouTube host and PiP fit; closed startup orphan retention gap | Android CI: eight regressions, lint, APK assembly; PRs #5/#6; device unavailable | 🟢 READY FOR FINAL LIVE ACCEPTANCE | One physical-device session covering the four existing issues |
| Death Loss v3 | C — nonempty scheduled acceptance missing | Audited installed v1.4.1, queue/write/recovery gates and native 18:00 scheduler; restored missing private nonsecret config; merged PR #19 | 65 tests; independent #17407 zero/paid/fulfilled/source checks and original verified inventory 10→9, 6→5 | 🟢 READY FOR FINAL LIVE ACCEPTANCE | Observe next genuine nonempty scheduled close and retain verified receipt |
| Betta Processing | B — competing versions/unproven current acceptance | Retained canonical V2.1; closed experimental PR #3; tightened exact identity, zero-stock authority, protected readback and archive proof; removed stale runtime instructions | 30 tests; seven current products read-only; 14/14 historical archive hashes | 🟢 READY FOR FINAL LIVE ACCEPTANCE | One genuinely new fish through approved V2.1 test, readback/archive/telemetry and resume check |
| Shipping Fulfilment V2 | B — draft PR #17 lacked tracking/handoff | Merged PR #17; preserved tracking end-to-end; durable intent/receipt protection; runnable default-read-only adapter and independent readback in PR #23 | 17 tests; six dry-runs; offline adapter capability and complete #17111 read-only state | 🟢 READY FOR FINAL LIVE ACCEPTANCE | One genuine dispatch through CLI, then restart/replay requiring DUPLICATE_NOOP |
| Shopify ↔ ShipStation Cost Sync | B — built, not accepted | Complete historical collision index; whole-order ambiguity holds; old-label aggregation; currency/type/precision checks; corrected two known orders and deployed tested source | 13 tests; 2,228 labels; 16,399–16,400 orders; two independent readbacks; repeat 30 matched/zero changes; PR #1 | ✅ CLOSED / BAU | None for engineering closure; two source tracking collisions are BAU exceptions |
| Google Merchant Center | B initially; D after live reader diagnosis | Independently categorized current eligibility; checkpointed standalone maintenance without unrelated AdHarbour commits; preserved strict reader guard | Fresh final census: 3,431 offers, 23 Google internal-image disapprovals, 52 pending; all affected image/landing URLs 200; 28 tests; healthy deployed Worker; PR #5 | 🔴 BLOCKED | Correct GMC reader app grant; preview must pass before accepting maintenance |
| Catalogue Integrity | B initially; D after finite physical audit | Repeatable private audit with livestock/plant/preorder exceptions; no guessed policy/stock/code changes | 2,279 products/2,739 variants; seven tests; zero unapproved retail CONTINUE; 41 physical balances +29 heavy-weight findings; PR #22 | 🔴 BLOCKED | Supply physical count/order reconciliation and packed-weight/ShipWeave facts for exact 70 findings |
| Gumtree Automation Engine | A — complete engine, stale operations | Closed manual-post engineering; verified registry/backup/live policy gates; corrected obsolete workshop/six reminders; separated catalogue queue | 174 tests; SQLite integrity/backup ok; five live product reads; correct zero-item fail-closed queue; PR #20 | ✅ CLOSED / BAU | None for engineering closure; manual listing decisions remain a small BAU queue |

## Closed today

- Gumtree Automation Engine. Five mapped products and three recorded listing instances are coherent; lack of activation policy correctly prevents new packages. No browser publisher is required in production.
- Shopify ↔ ShipStation Cost Sync. Controlled metadata corrections: #17111 actual/accounting AUD 24.62 (two active labels); #17037 actual AUD 51.18 (three labels), accounting allowance AUD 33.00. Independent reads verify changed values/types and unchanged order amounts/tracking. Unchanged repeat has zero writes and does not refresh timestamps.

## One-action closes

**StreamShelf:** install [StreamShelf build 102](https://github.com/cbnaquatics-spec/private-media-player/releases/tag/streamshelf-build-102) from merge 031da27 and complete [the one device session](https://github.com/cbnaquatics-spec/private-media-player/blob/main/docs/ACCEPTANCE.md): landscape/portrait PiP; interrupted/restarted download and resume; seek/position persistence; real YouTube retry/refusal handling. Record build/device/Android and outcomes. Issues #1–#4 deliberately remain open with linked CI/checklist evidence. Source retention tests cover seven-day startup cleanup without waiting a week on the device.

**Death Loss:** observe the next real nonempty 18:00 Australia/Sydney job 2900ada8-d36a-43e2-8243-be4c80e7bf90. Require CLOSED_VERIFIED, one daily-tag order, exact source references/lines/customer/discount, PAID/FULFILLED/$0 AUD/zero balance and frozen-before/fresh-after stock verification. Read-only same-date preview must identify the same order. An empty run does not count. Today's queue still had no October 2 batch at the final inspection.

**Betta:** use one genuinely new fish with already approved source/hero assets in the established V2.1 live-test path. Require exact tank/product/variant/location, source-linked new-fish authority before any zero-stock revival, protected fields unchanged, correct title/date/images/inventory, independent readback, archive hashes and telemetry. Resume the same ledger without a second mutation. The older seven-fish archive is historical evidence, not current acceptance.

**Shipping:** for the next genuinely dispatched source-authorized shipment, put its exact IDs/quantities/carrier/tracking into the private event file with notify_customer=false. From /Users/davidlo/openclaw-skills-v3 run the preflight and explicitly write-enabled acceptance/replay commands in [shipping closeout](../nta-shipping-fulfilment/docs/CLOSEOUT.md). Require READY → VERIFIED with stored fresh readback/PASS receipt → DUPLICATE_NOOP after restart. The runnable path uses the existing auth file/bridge; auth-file contents cannot enable writes. No real shipment was fulfilled during this review.

## External waits and blockers

- Google: all 23 AU disapprovals are image_link_internal_error with Google's no-action-needed/reprocess advice; 52 pending offers also wait for processing. All 46 affected URL checks pass. Account issues and missing shipping labels are zero. Do not replace working images or force review state.
- GMC maintenance: catalog reader rejects the actual read_orders,read_products,write_customers grant. Remove write_customers from the app identified by the dedicated Worker's SHOPIFY_CLIENT_ID, retaining read_products and optional read_orders; apply/reinstall the corrected grant if required. Changing account permissions is a human credential action under the mission rules. Then run the hosted read-only preview and require a complete census. No writer was dispatched in the failed closeout preview. Dedicated deployed version: 1e225e00-22a9-48cb-80ae-864be8d56356, /health HTTP 200; that does not prove reader integration.
- Catalogue: evidence/CATALOGUE_ACTIONS.csv contains exactly 70 blocking variant findings. Reconcile 41 tracked non-preorder physical balances against a real count and committed/open orders; measure and verify heavy routing for 29 shipped >5 kg net-weight variants with zero recorded weight. No packed weight, stock or commercial rate is invented.

## BAU operational queues

Gumtree: Blackworms NEEDS HUMAN REVIEW; Red Cherry ARCHIVE manually after account confirmation; White Caridina and Scarlet Blue Endler HOLD pending activation decisions; Pea Puffer ACTIVE in registry only, operator confirms live account state; held Betta conflict HOLD until exact identity/content decision. Fresh stocks are 0, 0, 84, 13, 18 respectively; none has a live activation policy. No ad publication or spend occurred.

Cost sync: labels se-201587772 and se-201588010 have tracking shared by orders 5519719334097 and 5520288743633. Whole candidate orders are held. Operator confirms dispatch ownership and repairs source tracking; existing metadata on those ambiguous orders is not certified. Wednesday 11:00 user launchd agent is loaded, host timezone Australia/Sydney, private env mode 600/launcher 700, logs and rollback source retained. Monthly carrier invoice/adjustment reconciliation is BAU: API purchased-label rate is not a guaranteed final carrier invoice. [ShipStation adjustment guidance](https://help.shipstation.com/hc/en-us/articles/29256492262683-ShipStation-Carrier-Adjustments).

Catalogue: 91 negative preorder/untracked/nonphysical balances are accounting exceptions, 56 zero-stock tank fish need sold/current identity review, and nine SKU/17 barcode duplicate active groups need supplier/operator facts. These are separate from the blocking physical/shipping queue. DENY protects zero-stock tank checkout; no bulk archival or invented identifier occurred.

## Canonical source, deployment and Git evidence

| System | Canonical source/runtime | Merged evidence |
|---|---|---|
| Shared skills | Davo01921/openclaw-skills; clean /Users/davidlo/openclaw-skills-v3 main | Gumtree PR20 merge 03bce3e; Death Loss PR19 merge 09fd5aa; Shipping PR17 merge aec8abd; Betta PR21 merge d4a7dd4; Catalogue PR22 merge 1b8f14f; shipping runner PR23 merge 42eab70 |
| StreamShelf | cbnaquatics-spec/private-media-player; isolated clean checkout in central workspace | PR5 merge 385ce44; PR6 merge 031da27; eight tests/lint/assembly pass in [PR CI](https://github.com/cbnaquatics-spec/private-media-player/actions/runs/36971999991); [final main CI](https://github.com/cbnaquatics-spec/private-media-player/actions/runs/36972857567) passed; release streamshelf-build-102 / StreamShelf-build-102.apk (SHA-256 7d7a028c718237f56a56adb52c00dc8e93b311ac164cf51c4b8feb22aa519f48) |
| Cost Sync | Davo01921/shopify-shipstation-sync main 7a33252; runtime ~/.local/share/nta-shipstation-sync | PR1 merged; main CI 36970898516 successful; installed sync.mjs SHA matches canonical source |
| GMC | ntashopmanager/AdHarbour backend-v0.2-cloudflare; dedicated projects/gmc-maintenance component in isolated clean worktree | PR5 merge ebbbc35; 28 component tests, strict TypeScript and backend CI 36968358450 pass; existing dedicated Worker deployed |

The clean shared main was fast-forwarded after merges. Fred's Death Loss Python files independently match canonical source byte-for-byte. Main workshop and Fred workspace Betta entrypoints now delegate to one canonical V2.1 path; obsolete support files are retained only for rollback. Gumtree's workshop and six reminder payloads now reflect manual-post operation, preserving schedules/product identities without triggering tasks. Runtime backups and pointer hashes are retained privately.

Pre-existing dirty generic OpenClaw and original AdHarbour working copies were preserved. Nine unrelated unpublished AdHarbour commits were not pushed or merged into this closeout. The GMC component was packaged independently from the existing remote branch. Experimental Betta V3 PR3 is formally CLOSED/deferred; its historical branch is retained. No closeout PR is left permanently nearly finished.

## Future backlog and recovery

Optional quality selection/FFmpeg/WorkManager, Betta quota-night automation, dashboards/richer reporting, live ShipWeave integration, invoice integration, broad SEO/photography and blanket code filling are deferred in each project's FUTURE_BACKLOG.md. Preserve the existing eligibility and biosecurity/dispatch restrictions. Owner-only commercial refund wording and packed/fragile-shipping decisions are not invented by engineering.

Each project's CLOSEOUT/SOP contains recovery. Keep intent ledgers after code rollback, independently reconcile unknown remote mutation outcomes, and never overwrite stock from a stale baseline. Cost-sync source backup is private; its metadata before values/types support exact reversible correction. GMC can suspend future applies via its existing ENABLE_APPLY=false deployment and restore pre-closeout dedicated Worker d78ecce5-ad4c-46dd-927f-076f66e88c9f. StreamShelf rollback uses an existing-signature APK while preserving app data; uninstall is destructive to its private library.

No customer messages, paid ads/model calls, supplier orders, inventory resets, ownership changes or credential disclosures were performed.
