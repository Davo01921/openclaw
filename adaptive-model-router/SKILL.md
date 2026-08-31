---
name: "adaptive-model-router"
description: "Routes deep tasks through Gemini→OpenAI failover and keeps light work on a safe route."
---

# Adaptive Model Router

Route each request through a configured agent topology with verified fallback behavior.

This is the shared execution-routing module for `nta-automation-orchestrator`. It selects a configured model route; it never grants product, Shopify, supplier, shipping, or customer-notification authority.

## Active routes

- **Mundane/lightweight:** handle on the stable `main` agent (`openai/gpt-5.6-sol`). Do not route to Llama until a constrained `light` agent is configured with no tools, lean local-model mode, and sufficient Ollama context.
- **In-depth:** dispatch to agent `deep`. Its configured primary is `google/gemini-3.5-flash` with `openai/gpt-5.6-sol` as an automatic fallback.

## Procedure

1. First classify deterministic work (arithmetic, payload construction, API calls, idempotency, comparisons and verification) as `NONE`; execute it without a model. Then classify any remaining request:
   - Mundane/lightweight: short rewriting, formatting, extraction, simple summaries, routine lookups, or low-risk clerical work.
   - In-depth: multi-step reasoning, coding, research synthesis, architecture, debugging, or consequential decisions.
2. Verify the target agent/model availability before dispatch. Never invent model identifiers.
3. For in-depth work, use the configured `deep` agent without a one-off model override. Explicit model overrides are strict and bypass the agent's automatic fallback policy.
4. If Gemini is rate-limited, out of quota, times out, or fails before producing a reply, allow the `deep` agent's configured OpenAI fallback to complete the task.
5. Avoid duplicate external actions after a partial provider failure.
6. Do not route tool-enabled or consequential work to the current Llama 3.2 model.
7. Mention a provider switch only when it affects quality, latency, cost, or completion.
8. Periodically retry Gemini through normal OpenClaw recovery behavior; do not hammer a quota-exhausted provider.

## Constraints

- `skill_workshop` manages reusable procedures; it does not execute tasks through a model parameter.
- Automatic failover is controlled by agent model configuration.
- A future `light` agent must be tool-free, use lean local-model mode, and set Ollama `num_ctx` to at least 16384 before Llama routing is enabled.
