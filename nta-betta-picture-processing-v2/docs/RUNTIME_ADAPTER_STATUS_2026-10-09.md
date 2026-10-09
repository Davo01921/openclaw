# Betta V2.1 runtime adapter status — 9 October 2026

Status: OFFLINE IMPLEMENTATION ONLY. The deployed end-to-end runtime cannot be
located inside this repository. This document states exactly what exists, what is
missing, and what must not be claimed.

## What this repository supplies

| Concern | Artefact | Executes? |
|---|---|---|
| State machine, evidence gates, title contract, mutation envelope | `scripts/betta_batch.py` | Deterministic library/CLI, no external I/O |
| Offline orchestration over injected adapters | `scripts/betta_runtime.py` | Deterministic library, no external I/O |
| Persistent telemetry | `scripts/betta_telemetry.py` | SQLite, local |
| Telemetry metrics | `scripts/betta_metrics.py` | Local read-only |
| General vision inference | `scripts/vision_review.py` | Shells to `openclaw infer model run` (external) |
| Bounded parallel vision | `scripts/vision_batch.py` | Threads over `vision_review.py` (external) |
| Grok hero generation | `scripts/grok_hero.py` | xAI HTTP API (external, paid) |
| Routing reference | `scripts/routing_reference.py` | Reference only |

The helpers validate evidence and plan work. They do not call Discord, Shopify or
the model services themselves.

## What is configured to execute the workflow

- Installed skill name: `betta-picture-processing`.
- Live Fred skill entry: `/Users/davidlo/.openclaw/workspace/fred/skills/betta-picture-processing/SKILL.md`.
- That entry is a thin delegator: it instructs the agent to read and follow the
  canonical source at `/Users/davidlo/openclaw-skills-v3/nta-betta-picture-processing-v2/`
  (this directory) and to use its scripts/references.
- `~/.openclaw/openclaw.json` enables `betta-picture-processing` and defines the
  `betta-vision-worker` sub-agent. Model selection is delegated to
  `adaptive-model-router`; no betta model slugs are pinned.
- Shopify mutation authority is routed through `nta-shopify-write-verifier` →
  `nta-shopify-product-writer` (skills, not executable adapters).

## Exact missing adapters / configuration

There is **no runnable end-to-end orchestrator and no concrete Shopify or Discord
adapter in this repository or its installed skill clone**. Specifically missing:

1. An executable driver that consumes `betta_batch.py execution-plan` and
   `betta_runtime.BettaRuntime`, collecting a Discord thread and persisting a real
   ledger. `BettaRuntime` is callable, but nothing in the deployed skill invokes it;
   orchestration today is the agent following prose.
2. A concrete `shopify.resolve` / `shopify.mutate` / `shopify.read` adapter with
   proven Admin/GraphQL scopes. The only declared boundary is the
   `nta-shopify-write-verifier` skill contract; the child writer/auditor pair has no
   callable adapter included here.
3. A concrete `source_store` (Discord attachment → immutable saved file) adapter.
4. A confirmed runtime identity check proving which provider/model actually served
   general vision/review calls (the code records what the envelope reports, but no
   live attestation is captured offline).

Until those exist and are exercised under the live acceptance flow, `betta_runtime`
must be treated as an offline-verified library, not a production runtime.

## What must not be claimed

- Do not claim standalone end-to-end completion.
- Do not claim production acceptance: only the one-new-fish live exercise in
  `CLOSEOUT.md` can close V2.1.
- Do not install, activate, restart, deploy or merge this work as production.
- Do not perform live Shopify writes, paid generation or secret retrieval to close
  the gap.

## Recovery

If a live run is interrupted, resume from the ledger checkpoint; reconcile any
inconclusive Shopify result by an independent read before any retry; back up
ledgers, telemetry SQLite and approved assets before workflow updates. The
deterministic modules are safe to copy in place; they make no external calls on
import.
