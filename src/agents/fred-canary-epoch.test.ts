import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { expect, it, vi } from "vitest";

it("treats deadline zero as a durable epoch and rejects legacy canary state", async () => {
  vi.resetModules();
  const dir = mkdtempSync(path.join(tmpdir(), "fred-durable-egress-"));
  writeFileSync(
    path.join(dir, "state.json"),
    JSON.stringify({
      version: 1,
      startedAtMs: 1,
      deadlineMs: Date.now() + 3_600_000,
      eligibleCalls: 50,
      observedCalls: 50,
      completedJobs: 50,
      stoppedAtMs: Date.now(),
      stopReason: "50_SUCCESSFUL_CALLS",
    }),
  );
  process.env.OPENCLAW_FRED_ATTRIBUTION_CANARY = "1";
  process.env.OPENCLAW_FRED_ATTRIBUTION_DIR = dir;
  delete process.env.OPENCLAW_FRED_ATTRIBUTION_DEADLINE_MS;
  const { wrapStreamFnWithFredAttributionCanary } = await import("./fred-attribution-canary.js");
  const baseStreamFn = vi.fn(() => undefined) as never;
  const wrapped = wrapStreamFnWithFredAttributionCanary({
    streamFn: baseStreamFn,
    agentId: "fred",
    sessionId: "session",
    runId: "run",
  });
  wrapped({} as never, {} as never, {} as never);
  await vi.waitFor(() => {
    const state = JSON.parse(readFileSync(path.join(dir, "state.json"), "utf8"));
    expect(state).toMatchObject({
      deadlineMs: 0,
      eligibleCalls: 1,
      observedCalls: 0,
      completedJobs: 0,
    });
    expect(state.stoppedAtMs).toBeUndefined();
  });
});
