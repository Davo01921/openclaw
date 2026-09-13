---
name: "adaptive-model-router"
version: "2.0"
description: "Canonical model-selection authority for NTA skills: prefer deterministic execution, classify model-required work by capability/risk, and preserve the configured OpenAI→Qwen failover policy."
---

# Adaptive Model Router — v2.0

## Authority

This skill is the single canonical authority for model selection across the NTA skills repository.

Whenever any NTA skill or workflow needs an AI model — including when a specialist skill is invoked directly instead of through `nta-automation-orchestrator` — model selection must resolve through this router first.

Specialist skills may declare what a phase needs, for example:

- text or vision capability;
- structured extraction;
- ordinary reasoning;
- deep reasoning;
- read-only review;
- tool access;
- latency or cost sensitivity.

Specialist skills must not independently choose a provider, hard-code a model slug, invent a fallback chain, or silently escalate to a more expensive route.

This router selects execution capacity only. It never grants product, Shopify, supplier, shipping, customer-notification, refund, publishing, or other mutation authority.

## Current provider policy

The intended provider/failover order is:

1. **OpenAI / ChatGPT configured route — primary**
2. **Qwen Token Plan — first fallback**
3. **Qwen API — backup fallback**

Exact provider and model identifiers must come from live OpenClaw configuration and execution metadata. Do not guess or duplicate secret/runtime configuration in this repository.

The previous Gemini-primary `deep` route and proposed Llama route are retired policy. Do not route to Gemini or Llama unless David explicitly changes the policy and the live OpenClaw configuration confirms the new route.

If the configured runtime does not match the intended provider order above, report the discrepancy rather than pretending the requested policy is active.

## Routing classes

Classify each model-bearing phase independently. Do not label an entire multi-stage workflow with one model class when some phases are deterministic or materially different.

| Class | Model use | Typical work |
| --- | --- | --- |
| `NONE` | No model | Arithmetic, exact comparisons, payload construction, API calls, idempotency checks, state transitions, deterministic validation, formatters, read-back assertions |
| `LIGHT` | Lowest capable configured route | Clean extraction, short rewriting, routine summarisation, obvious low-risk interpretation |
| `STANDARD` | Normal configured reasoning route | Product/content work, ordinary business reasoning, contained implementation/debugging, routine research synthesis |
| `DEEP` | Stronger reasoning/effort where the runtime supports it | Ambiguous identity, contradictory evidence, difficult debugging, cross-module diagnosis, consequential judgment |
| `CRITICAL_REVIEW` | Strongest available bounded review | Security/integrity issues, destructive or irreversible decisions, architecture ambiguity, migrations, unresolved high-consequence conflicts |

`CRITICAL_REVIEW` is advisory/review capacity. It does not itself authorise a write, deployment, refund, deletion, supplier order, publication, or other consequential mutation.

## Procedure

1. **Remove deterministic work first.** If code, a rule, an exact API read, or a comparison can answer the phase reliably, return `NONE` and do not consume model capacity.
2. **Identify required capabilities.** Record whether the phase needs text, vision, tools, long context, structured output, or read-only reasoning.
3. **Apply a risk floor.** A task that looks simple but involves security, credentials, destructive actions, legal/compliance judgment, billing, schema/data migration, production release/rollback, or another high-consequence decision must not be routed as `LIGHT`.
4. **Choose the smallest sufficient class.** Do not use deep reasoning merely for reassurance.
5. **Resolve through live configuration.** Use the configured OpenClaw route that satisfies the class and capability requirements while preserving the OpenAI → Qwen Token Plan → Qwen API provider policy.
6. **Preserve fallback behaviour.** Avoid one-off model overrides when they would bypass the configured automatic fallback chain.
7. **Escalate only for a reason.** A provider failure should trigger the configured provider fallback. A genuine reasoning failure, unresolved ambiguity, or risk escalation may raise the routing class. Do not repeatedly retry the same failed reasoning prompt at the same class without new evidence.
8. **Avoid duplicate external actions.** If a provider fails after a possibly completed mutation, verify state before any retry.
9. **Attest actual execution.** Never claim a provider/model actually handled the phase unless execution metadata confirms it.

## Vision and tool constraints

A route is not eligible merely because it is cheap.

- Vision phases require a route that actually supports the required image input/review surface.
- Tool-enabled or consequential phases require a route permitted to use the necessary tools safely.
- If a fallback provider lacks a required capability, skip that route for the affected phase rather than degrading silently.
- Deterministic code remains authoritative for exact title assembly, arithmetic, state transitions, payloads, validation and read-back checks even when a model produced upstream evidence.

## Direct-invocation rule

A specialist skill invoked directly must behave as though it were under `nta-automation-orchestrator` for model routing:

1. identify deterministic phases;
2. send only genuinely model-required phases to `adaptive-model-router`;
3. consume the resolved route/class;
4. retain its own domain rules and mutation authority boundaries.

Phrases in specialist skills such as `cheap model`, `reasoning reviewer`, `stronger model`, `vision model`, or similar are capability hints only. They do not override this router.

## Observability contract

Where telemetry is available, record at least:

```yaml
routing:
  class: NONE | LIGHT | STANDARD | DEEP | CRITICAL_REVIEW
  capability_requirements: []
  requested_route:
  actual_provider:
  actual_model:
  fallback_used: false
  escalation_reason:
  execution_attested: false
```

Requested route and actual execution are different facts. Provider/model fields must remain unknown when runtime metadata does not prove them.

## Constraints

- `skill_workshop` manages reusable procedures; it does not itself choose a provider/model for task execution.
- Automatic provider failover is controlled by live OpenClaw agent/model configuration.
- Repository skills may define model eligibility and required capabilities, but this router owns the selection decision.
- Runtime configuration is the execution truth; this file is the routing-policy truth. If they diverge, surface the mismatch.
