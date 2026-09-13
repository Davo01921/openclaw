import { describe, expect, it, vi } from "vitest";
import {
  createProviderRequestReadyObserver,
  providerRequestReadyObserver,
  type ProviderRequestReadyFailure,
} from "./provider-request-ready-observer.js";

const identity = {
  agentId: "fred",
  sessionId: "session-1",
  runId: "run-1",
  taskId: "task-1",
  modelCallId: "call-1",
  traceId: "trace-1",
};

describe("provider request ready observer", () => {
  it("defaults off and requires an explicitly allowed agent", () => {
    expect(
      createProviderRequestReadyObserver({
        options: {},
        provider: "provider",
        model: "model",
        egress: "test",
      }),
    ).toBeUndefined();

    const options = {};
    providerRequestReadyObserver.set(options, {
      identity: { ...identity, agentId: "main" },
      allowedAgentIds: ["fred"],
      observer: vi.fn(),
    });
    expect(
      createProviderRequestReadyObserver({
        options,
        provider: "provider",
        model: "model",
        egress: "test",
      }),
    ).toBeUndefined();
  });

  it("carries identity and exposes a deeply read-only request view", () => {
    const options = {};
    const request = { input: [{ content: "private-marker" }] };
    const before = JSON.stringify(request);
    const observer = vi.fn((_context, view) => {
      expect(() => {
        (view as { input: Array<{ content: string }> }).input[0]!.content = "changed";
      }).toThrow();
    });
    providerRequestReadyObserver.set(options, {
      identity,
      allowedAgentIds: ["fred"],
      observer,
    });
    createProviderRequestReadyObserver({
      options,
      provider: "provider-a",
      model: "model-a",
      egress: "responses-sdk",
    })?.(request, { payloadVariant: "initial" });
    expect(observer).toHaveBeenCalledWith(
      {
        ...identity,
        provider: "provider-a",
        model: "model-a",
        egress: "responses-sdk",
        payloadVariant: "initial",
      },
      expect.anything(),
    );
    expect(JSON.stringify(request)).toBe(before);
  });

  it("fails open without carrying request-derived errors across the boundary", async () => {
    const failures: ProviderRequestReadyFailure[] = [];
    const options = {};
    providerRequestReadyObserver.set(options, {
      identity,
      allowedAgentIds: ["fred"],
      observer: () => {
        throw new Error("private-marker");
      },
      onFailure: (failure) => failures.push(failure),
    });
    expect(() =>
      createProviderRequestReadyObserver({
        options,
        provider: "provider",
        model: "model",
        egress: "test",
      })?.({ input: "private-marker" }),
    ).not.toThrow();
    expect(failures).toEqual([{ kind: "observer_exception" }]);

    const timeoutOptions = {};
    providerRequestReadyObserver.set(timeoutOptions, {
      identity,
      allowedAgentIds: ["fred"],
      observer: () => new Promise(() => undefined),
      onFailure: (failure) => failures.push(failure),
      timeoutMs: 5,
    });
    createProviderRequestReadyObserver({
      options: timeoutOptions,
      provider: "provider",
      model: "model",
      egress: "test",
    })?.({});
    await vi.waitFor(() => expect(failures).toContainEqual({ kind: "observer_timeout" }));
  });
});
