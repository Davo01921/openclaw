import { describe, expect, it, vi } from "vitest";
import { createResponsesStreamWithEncryptedContentRetry } from "./openai-responses-replay-internal.js";
import {
  createProviderRequestReadyObserver,
  providerRequestReadyObserver,
} from "./provider-request-ready-observer.js";

const model = { provider: "provider-a", api: "openai-responses", id: "model-a" } as never;

function mockClient(create: (request: unknown) => void) {
  return {
    responses: {
      create: (request: unknown) => ({
        withResponse: async () => {
          create(request);
          return {
            data: {
              async *[Symbol.asyncIterator]() {
                yield { type: "response.completed" };
              },
            },
            response: { status: 200 },
          };
        },
      }),
    },
  } as never;
}

describe("provider request observer at the Responses egress seam", () => {
  it("observes the exact post-transform SDK request with provider-neutral identity", async () => {
    const options = {};
    const seen: string[] = [];
    providerRequestReadyObserver.set(options, {
      identity: { agentId: "fred", sessionId: "s", runId: "r", modelCallId: "c" },
      allowedAgentIds: ["fred"],
      observer: (_context, request) => {
        seen.push(JSON.stringify(request));
      },
    });
    const observeProviderRequest = createProviderRequestReadyObserver({
      options,
      provider: "provider-a",
      model: "model-a",
      egress: "responses-sdk",
    });
    const request = { model: "model-a", input: [{ role: "user", content: "private" }] };
    let sent = "";
    const { stream } = await createResponsesStreamWithEncryptedContentRetry({
      client: mockClient((value) => {
        sent = JSON.stringify(value);
      }),
      request: request as never,
      requestOptions: undefined,
      model,
      observeProviderRequest,
    });
    for await (const _event of stream) {
      // Drain the synthetic provider stream.
    }
    expect(seen).toEqual([sent]);
  });

  it("leaves provider dispatch unchanged when the observer fails", async () => {
    const options = {};
    providerRequestReadyObserver.set(options, {
      identity: { agentId: "fred" },
      allowedAgentIds: ["fred"],
      observer: () => {
        throw new Error("observer failure");
      },
    });
    const observeProviderRequest = createProviderRequestReadyObserver({
      options,
      provider: "provider-b",
      model: "model-b",
      egress: "responses-sdk",
    });
    const create = vi.fn();
    await createResponsesStreamWithEncryptedContentRetry({
      client: mockClient(create),
      request: { model: "model-b", input: [] } as never,
      requestOptions: undefined,
      model,
      observeProviderRequest,
    });
    expect(create).toHaveBeenCalledOnce();
  });
});
