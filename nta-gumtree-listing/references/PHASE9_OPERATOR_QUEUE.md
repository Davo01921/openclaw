# Phase 9 — Gumtree Operator Queue

## Purpose

Phase 9 changes the live rollout model from browser automation to operator-assisted posting.

OpenClaw prepares complete, deterministic Gumtree posting packages. David manually creates/posts the ad in Gumtree. OpenClaw then records the Gumtree listing reference and verifies the handoff.

No automated Gumtree browser interaction is required by this phase.

## Posting days

New operator queues are generated only on:

- Thursday
- Friday
- Saturday

Sunday through Wednesday return an empty queue.

## Daily limit

A queue contains at most 3 ads per day.

Three is a maximum, not a target. If zero, one, or two products are genuinely suitable, the queue contains only those products.

## Eligibility

An item enters the operator queue only when:

1. identity is already `MAPPED` or `MANAGED`;
2. deterministic reconciliation produces a safe draft action;
3. no review-only reconciliation outcome applies;
4. the Phase 5 listing plan is `READY`;
5. title, description, price, category, location, images and source fingerprint are present.

Uncertain or malformed snapshots fail closed and are skipped.

## Ranking

When more than three safe candidates exist, ranking is deterministic:

1. `CORE_TRAFFIC`
2. `HIGH`
3. `NORMAL`
4. `LOW`

Within the same priority, new draft creation is preferred before draft updates, followed by stable ad/product identifiers.

## Operator lifecycle

```text
READY_TO_POST
    ↓ David manually posts to Gumtree
POSTED
    ↓ independent verification succeeds
VERIFIED
```

`READY_TO_POST → POSTED` requires a Gumtree listing ID or URL supplied after the manual post.

`POSTED → VERIFIED` requires explicit successful verification.

Skipping lifecycle states is not permitted.

## Authority boundary

Phase 9 has:

- no publish authority;
- no Gumtree browser automation;
- no paid promotion authority;
- no automatic pause/remove/relist authority;
- no automatic mutation of management state.

The existing browser-writer code remains dormant for possible future approved integrations, but Phase 9 does not call it.

## Intended OpenClaw behavior

On Thursday, Friday, and Saturday, OpenClaw may run the queue generator and present up to three complete ad packages for manual posting.

After David posts an ad, David supplies the Gumtree URL or listing ID. OpenClaw records the handoff and moves the queue item to `POSTED`, then to `VERIFIED` only after verification succeeds.
