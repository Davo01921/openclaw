import { describe, expect, it, vi } from "vitest";
import { ProviderAttributionQueue, materialityForTokens } from "./provider-attribution-queue.js";

const context = {
  agentId: "fred",
  sessionId: "session",
  runId: "run",
  modelCallId: "call",
  traceId: "trace",
  provider: "provider-a",
  model: "model-a",
  egress: "responses-sdk",
  payloadVariant: "initial",
};

describe("off-path provider attribution queue", () => {
  it("honors default-off, kill-switch, and Fred-only gates", async () => {
    const disabled = new ProviderAttributionQueue(
      { enabled: false, killSwitch: false, allowedAgentIds: ["fred"], maxInFlight: 2 },
      vi.fn(),
    );
    expect(disabled.observe(context, {}, 1)).toBe(false);
    expect(disabled.metrics.errorsByReason.DISABLED).toBe(1);
    await disabled.shutdown();

    const killed = new ProviderAttributionQueue(
      { enabled: true, killSwitch: true, allowedAgentIds: ["fred"], maxInFlight: 2 },
      vi.fn(),
    );
    expect(killed.observe(context, {}, 1)).toBe(false);
    expect(killed.metrics.errorsByReason.KILL_SWITCH).toBe(1);
    await killed.shutdown();

    const scoped = new ProviderAttributionQueue(
      { enabled: true, killSwitch: false, allowedAgentIds: ["fred"], maxInFlight: 2 },
      vi.fn(),
    );
    expect(scoped.observe({ ...context, agentId: "main" }, {}, 1)).toBe(false);
    expect(scoped.metrics.errorsByReason.UNEXPECTED_AGENT).toBe(1);
    await scoped.shutdown();
  });

  it("counts off-thread, does not mutate input, and emits metadata only", async () => {
    const marker = `PRIVATE_${Date.now()}`;
    const request = { input: [{ content: marker }] };
    const before = JSON.stringify(request);
    const results: unknown[] = [];
    const queue = new ProviderAttributionQueue(
      { enabled: true, killSwitch: false, allowedAgentIds: ["fred"], maxInFlight: 4 },
      (result) => {
        results.push(result);
      },
    );
    expect(queue.observe(context, request, 1)).toBe(true);
    await vi.waitFor(() => expect(queue.metrics.eventsCompleted).toBe(1), { timeout: 10_000 });
    expect(JSON.stringify(request)).toBe(before);
    expect(JSON.stringify(results)).not.toContain(marker);
    await queue.shutdown();
  });

  it("bounds the queue and rejects duplicate attempts while failing open", async () => {
    const queue = new ProviderAttributionQueue(
      { enabled: true, killSwitch: false, allowedAgentIds: ["fred"], maxInFlight: 1 },
      vi.fn(),
    );
    expect(queue.observe(context, { input: "x".repeat(100_000) }, 1)).toBe(true);
    expect(queue.observe(context, {}, 1)).toBe(false);
    expect(queue.metrics.errorsByReason.DUPLICATE_ATTEMPT).toBe(1);
    expect(queue.observe({ ...context, modelCallId: "call-2" }, {}, 1)).toBe(false);
    expect(queue.metrics.errorsByReason.QUEUE_FULL).toBe(1);
    await queue.shutdown();
  });

  it("uses deterministic token-scale materiality", () => {
    expect(materialityForTokens(9_999)).toBe("LOW");
    expect(materialityForTokens(10_000)).toBe("MEDIUM");
    expect(materialityForTokens(49_999)).toBe("MEDIUM");
    expect(materialityForTokens(50_000)).toBe("HIGH");
  });
});
