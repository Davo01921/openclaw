# NTA Project Portfolio — 5 OCTOBER 2026

> Current portfolio source of truth. Progress percentages are management estimates for prioritisation; they are **not** substitutes for acceptance evidence.

**Tracked initiatives: 35**

| Category | Count | Share |
|---|---:|---:|
| PRODUCTION / DONE | 14 | 40.0% |
| FINAL ACCEPTANCE / MONITORING | 2 | 5.7% |
| ACTIVELY BUILDING | 5 | 14.3% |
| BLOCKED / OPERATIONAL | 2 | 5.7% |
| BACKLOG / UPCOMING | 10 | 28.6% |
| CANCELLED / SUPERSEDED | 2 | 5.7% |

## Portfolio

### PRODUCTION / DONE (14)

| Project | Status | Progress | Current state | Next step |
|---|---|---:|---|---|
| NTA Shipping Gate v1 | PRODUCTION | 100% | Production since 2 Oct; deterministic SHIP / REVIEW / HOLD gate. | BAU; activate carrier writes only after direct-dispatch acceptance. |
| ShipWeave / ASR replacement | PRODUCTION | 100% | Authoritative Shopify checkout engine; 77/77 tests passed at cutover. | BAU monitoring. |
| ShipStation → Shopify cost sync | PRODUCTION | 100% | Closed / BAU; production acceptance complete. | Routine reconciliation only. |
| Aqua Premium order processor | PRODUCTION | 100% | V1.2.1 production accepted / closed; guarded supplier flow. | Mon/Tue/Wed 07:00 scheduled review is BAU. |
| NTA Product Generation v1.2 | PRODUCTION | 100% | Guarded Shopify CREATE is production-proven; architecture frozen. | Extend only for proven recurring defects. |
| StoreUse v1.1 | PRODUCTION | 100% | Core store-use automation complete. | Routine use. |
| Gumtree Automation Engine | PRODUCTION | 100% | Closed / BAU; small manual catalogue queue remains. | Manual listing decisions only. |
| DYMO / Shopify line-item labels | PRODUCTION | 100% | 16-label sheets + Shopify print tags live. | BAU. |
| NTA POS v1 | PRODUCTION | 100% | Closed / production / BAU after genuine sale #17435; 314/314 tests. | Future commercial V2 is separate. |
| StreamShelf | PRODUCTION | 100% | Physical-device acceptance passed 3 Oct; v1 closed / BAU. | Optional future features stay deferred. |
| Death Loss v3 | PRODUCTION | 100% | Closed / production / BAU after genuine scheduled close. | Normal 18:00 operation only. |
| TierWeave | PRODUCTION | 100% | Live and accepted; replaces standalone Koala upsell build. | Routine pricing maintenance. |
| Shipping Fulfilment v2 | PRODUCTION | 100% | Closed / BAU; live replay waived as closure blocker. | Optional BAU confidence replay only. |
| Live Transcriber private v1 | PRODUCTION | 100% | Build 48 accepted private baseline; engineering project closed / BAU. | Commercial/public phase is separate future work. |

### FINAL ACCEPTANCE / MONITORING (2)

| Project | Status | Progress | Current state | Next step |
|---|---|---:|---|---|
| Betta Processing v2.1 | FINAL ACCEPTANCE | 90% | Canonical V2.1; one genuine new-fish acceptance remains. | Run one new fish through readback/archive/telemetry and close. |
| AdHarbour v0.5 | MONITORING | 90% | Read-only pilot live; 5 Oct scheduled run failed, manual recovery passed; v0.6 staging isolated. | Wait for genuine 12 Oct run; review on 13 Oct before rollout. |

### ACTIVELY BUILDING (5)

| Project | Status | Progress | Current state | Next step |
|---|---|---:|---|---|
| NTA Internal Finance | ACTIVE | 80% | Active / shadow accounting; QuickBooks remains system of record. | Finish refund/provider cases, reconciliation and remaining connectors. |
| Direct Carrier Dispatch | ACTIVE | 85% | Implemented inside Shipping Gate; shadow mode; booking/fulfilment writes off; prod carrier creds absent. | Add carrier credentials incl. MyTeamGE; prove live quotes before writes. |
| NTA Club | ACTIVE | 35% | Phase 1 contract + mobile foundations complete; no blockers. | Build Shopify customer auth/integration, then focused MVP. |
| NTA Order Orchestrator | ACTIVE | 60% | Supersedes old Order Status Processor; Phase 3 specialist integration is partial. | Finish Phase 3, production D1/migrations and controlled shadow acceptance. |
| OpenClaw AI Observatory | ACTIVE | 80% | Local metadata-first observability and routing governance are operational. | Continue routing attribution, provider reconciliation and drift checks. |

### BLOCKED / OPERATIONAL (2)

| Project | Status | Progress | Current state | Next step |
|---|---|---:|---|---|
| Google Merchant Center cleanup | BLOCKED | 45% | Cleanup is operational; Google processing / maintenance acceptance still incomplete. | Let Google reprocess; verify remaining issues and standalone maintenance acceptance. |
| Catalogue Integrity | BLOCKED | 55% | Finite audit complete; exact blocking facts remain. | Reconcile 41 physical balances + 29 heavy packed-weight facts. |

### BACKLOG / UPCOMING (10)

| Project | Status | Progress | Current state | Next step |
|---|---|---:|---|---|
| NTA POS V2 commercial platform | PLANNED | 5% | Independent livestock-retail platform fully specified; documentation only. | Do not start implementation until explicitly authorised. |
| NTA Vision (YOLO11) | UPCOMING | 10% | Android on-device vision proof-of-concept defined; not yet built. | Fork YOLO11 Android demo after higher-priority core work. |
| AI Agent Supervisor / Telegram | IDEA | 0% | Control-plane concept for reading agent results and feeding next prompts. | Select orchestration approach; create repo only when scope is frozen. |
| Aqua Premium daily inventory sync | BACKLOG | 10% | Supplier quantity differences → Shopify stock concept. | Build only if operational need justifies it. |
| RealtimeStack replacement | BACKLOG | 0% | Potential recurring-cost removal. | Do not start yet. |
| Unattended pickup / micro-store | BACKLOG | 0% | Idea / discovery. | No engineering commitment yet. |
| HomeOS | DISCOVERY | 10% | Private home/family assistant architecture and integrations. | Design/privacy work only; avoid scope creep. |
| StampOS | DISCOVERY | 5% | Privacy-first stamp collection / catalogue system is in planning. | Keep local-first privacy architecture; implementation later. |
| 90-day NTA growth plan | BACKLOG | 0% | Business initiative rather than current engineering priority. | Revisit after operational closures. |
| Live Transcriber commercial/public | DEFERRED | 0% | Private v1 is closed; public/commercial release is explicitly separate. | Revisit in a later phase, not as BAU work. |

### CANCELLED / SUPERSEDED (2)

| Project | Status | Progress | Current state | Next step |
|---|---|---:|---|---|
| Koala Upsell Replacement | CANCELLED | 100% | Cancelled; TierWeave is the production replacement. | No separate build. |
| Legacy Order Status Processor | SUPERSEDED | 100% | Old Flow-centric concept superseded by NTA Order Orchestrator. | Do not restart the legacy design. |

## Important status corrections made on 5 October 2026

- **NTA POS v1 is CLOSED / PRODUCTION / BAU** after genuine Shopify sale **#17435**; commercial V2 is a separate planned project.
- **StreamShelf is CLOSED / BAU** after the 3 October physical-device acceptance session.
- **Live Transcriber private v1 is CLOSED / BAU** at accepted Build 48; commercial/public work is future scope.
- **ShipStationReplacement is a meta/archive repo.** The real implementation is **Direct Carrier Dispatch inside `nta-shipping-gate`**.
- **Direct Carrier Dispatch is not production-accepted yet.** Production carrier credentials are absent; booking, fulfilment writes and notifications remain off. MyTeamGE/TGE onboarding is part of this workstream.
- **Order Status Processor is superseded.** The active successor is **NTA Order Orchestrator**, currently in Phase 3 specialist integration.
- **AdHarbour is moved from ordinary active build to monitoring/final acceptance.** The first genuine 5 October schedule failed at Merchant collection; manual recovery succeeded. The next genuine gate is 12 October, with review on 13 October.
- **NTA Vision is moved to upcoming/backlog** because the Android YOLO11 proof-of-concept is defined but not yet built.
- **Catalogue Integrity** is now tracked explicitly as a blocked operational workstream.
- **NTA POS V2**, **AI Agent Supervisor / Telegram**, **StampOS**, and the **Live Transcriber commercial/public phase** are added to the upcoming portfolio.

## Immediate focus — next 2–4 weeks

1. NTA Internal Finance — finish refund/provider acceptance and remaining connectors.
2. Direct Carrier Dispatch — add production carrier credentials safely, complete MyTeamGE/TGE plug-in readiness, prove live quotes, keep booking off until accepted.
3. AdHarbour — do not change production before the next genuine 12 October schedule unless a real defect requires it; review on 13 October.
4. NTA Order Orchestrator — finish Phase 3, production D1/migrations and controlled shadow acceptance.
5. Betta Processing v2.1 — run one genuine new fish and close if evidence passes.
6. NTA Club — proceed to Shopify customer authentication/integration after the above operational gates.

## Evidence basis

This update was reconciled against the accessible GitHub repositories and current branches, including `nta-pos`, `nta-shipping-gate`, `ShipStationReplacement`, `nta-club`, `nta-order-orchestrator`, `nta-quarterly-accountant-pack`, `live-transcriber`, `nta-product-generation`, `shopify-shipstation-sync`, `shopify-line-item-labels`, `openclaw-skills`, `agent-memory`, `ai-observability`, `ntashopmanager/AdHarbour`, `cbnaquatics-spec/private-media-player` and `cbnaquatics-spec/shipweave`.
