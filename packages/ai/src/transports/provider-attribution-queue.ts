import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { Worker } from "node:worker_threads";
import type { ProviderRequestReadyContext } from "./provider-request-ready-observer.js";

export type AttributionDropReason =
  | "DISABLED"
  | "KILL_SWITCH"
  | "UNEXPECTED_AGENT"
  | "QUEUE_FULL"
  | "WORKER_UNAVAILABLE"
  | "WORKER_CRASH"
  | "TOKENIZER_EXCEPTION"
  | "SHUTTING_DOWN"
  | "DUPLICATE_ATTEMPT"
  | "SERIALIZE_FAILED";

export type AttributionResult = Readonly<{
  context: ProviderRequestReadyContext;
  attemptId: string;
  attemptSequence: number;
  attemptType: string;
  tokenCount: number;
  serializedBytes: number;
  queueDelayMs: number;
  tokenizerRuntimeMs: number;
  materiality: "LOW" | "MEDIUM" | "HIGH";
  quality: "LOCALLY_CALCULATED";
}>;

export type AttributionMetrics = {
  eventsObserved: number;
  eventsCompleted: number;
  eventsDropped: number;
  queueDepth: number;
  maxQueueDepth: number;
  failOpenEvents: number;
  errorsByReason: Record<string, number>;
  synchronousOverheadMs: number[];
  queueDelayMs: number[];
  workerRuntimeMs: number[];
  tokenizerRuntimeMs: number[];
  databaseWriteRuntimeMs: number[];
};

export type AttributionQueueConfig = Readonly<{
  enabled: boolean;
  killSwitch: boolean;
  allowedAgentIds: readonly string[];
  maxInFlight: number;
  maxSeenAttempts?: number;
  workerUrl?: URL;
}>;

type Pending = {
  context: ProviderRequestReadyContext;
  attemptId: string;
  attemptSequence: number;
  attemptType: string;
  enqueuedAt: number;
};

export function materialityForTokens(tokens: number): "LOW" | "MEDIUM" | "HIGH" {
  if (tokens < 10_000) return "LOW";
  if (tokens < 50_000) return "MEDIUM";
  return "HIGH";
}

function resolveDefaultWorkerUrl(): URL {
  const sibling = new URL("./provider-attribution-worker.mjs", import.meta.url);
  const candidates: string[] = [fileURLToPath(sibling)];
  let dir = path.dirname(fileURLToPath(import.meta.url));
  for (let depth = 0; depth < 7; depth += 1) {
    candidates.push(path.join(dir, "provider-attribution-worker.mjs"));
    candidates.push(path.join(dir, "dist", "provider-attribution-worker.mjs"));
    candidates.push(path.join(dir, "packages", "ai", "dist", "provider-attribution-worker.mjs"));
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  for (const candidate of candidates) {
    try {
      if (existsSync(candidate)) return pathToFileURL(candidate);
    } catch {
      // Continue probing known immutable-build layouts.
    }
  }
  return sibling;
}

export class ProviderAttributionQueue {
  readonly metrics: AttributionMetrics = {
    eventsObserved: 0,
    eventsCompleted: 0,
    eventsDropped: 0,
    queueDepth: 0,
    maxQueueDepth: 0,
    failOpenEvents: 0,
    errorsByReason: {},
    synchronousOverheadMs: [],
    queueDelayMs: [],
    workerRuntimeMs: [],
    tokenizerRuntimeMs: [],
    databaseWriteRuntimeMs: [],
  };
  private readonly pending = new Map<string, Pending>();
  private readonly seen = new Set<string>();
  private readonly seenOrder: string[] = [];
  private worker?: Worker;
  private shuttingDown = false;

  constructor(
    private readonly config: AttributionQueueConfig,
    private readonly onResult: (result: AttributionResult) => void | Promise<void>,
  ) {
    if (config.enabled && !config.killSwitch) this.startWorker();
  }

  private startWorker(): void {
    try {
      this.worker = new Worker(this.config.workerUrl ?? resolveDefaultWorkerUrl());
      this.worker.unref();
      this.worker.on("message", (message) => this.handleMessage(message));
      this.worker.on("error", () => this.failWorker("WORKER_CRASH"));
      this.worker.on("exit", (code) => {
        if (code !== 0 && !this.shuttingDown) this.failWorker("WORKER_CRASH");
      });
    } catch {
      this.drop("WORKER_UNAVAILABLE");
    }
  }

  observe(
    context: ProviderRequestReadyContext,
    request: Readonly<object>,
    attemptSequence: number,
  ): boolean {
    const started = performance.now();
    this.metrics.eventsObserved += 1;
    const finish = (accepted: boolean) => {
      this.metrics.synchronousOverheadMs.push(performance.now() - started);
      return accepted;
    };
    if (!this.config.enabled) {
      this.drop("DISABLED");
      return finish(false);
    }
    if (this.config.killSwitch) {
      this.drop("KILL_SWITCH");
      return finish(false);
    }
    if (!context.agentId || !this.config.allowedAgentIds.includes(context.agentId)) {
      this.drop("UNEXPECTED_AGENT");
      return finish(false);
    }
    if (this.shuttingDown) {
      this.drop("SHUTTING_DOWN");
      return finish(false);
    }
    if (!this.worker) {
      this.drop("WORKER_UNAVAILABLE");
      return finish(false);
    }
    const attemptType = context.payloadVariant ?? "unknown";
    const attemptId = `${context.modelCallId ?? context.traceId ?? "unknown"}:${attemptSequence}:${attemptType}`;
    if (this.seen.has(attemptId)) {
      this.drop("DUPLICATE_ATTEMPT");
      return finish(false);
    }
    if (this.pending.size >= this.config.maxInFlight) {
      this.drop("QUEUE_FULL");
      return finish(false);
    }
    let payload: string;
    try {
      payload = JSON.stringify(request);
    } catch {
      this.drop("SERIALIZE_FAILED");
      return finish(false);
    }
    this.rememberAttempt(attemptId);
    this.pending.set(attemptId, {
      context,
      attemptId,
      attemptSequence,
      attemptType,
      enqueuedAt: performance.now(),
    });
    this.metrics.queueDepth = this.pending.size;
    this.metrics.maxQueueDepth = Math.max(this.metrics.maxQueueDepth, this.pending.size);
    try {
      this.worker.postMessage({ jobId: attemptId, request: payload });
      return finish(true);
    } catch {
      this.pending.delete(attemptId);
      this.metrics.queueDepth = this.pending.size;
      this.drop("WORKER_UNAVAILABLE");
      return finish(false);
    }
  }

  private rememberAttempt(attemptId: string): void {
    this.seen.add(attemptId);
    this.seenOrder.push(attemptId);
    const maxSeen = Math.max(this.config.maxInFlight, this.config.maxSeenAttempts ?? 4_096);
    while (this.seenOrder.length > maxSeen) {
      const oldest = this.seenOrder.shift();
      if (oldest && !this.pending.has(oldest)) this.seen.delete(oldest);
    }
  }

  private handleMessage(message: Record<string, unknown>): void {
    const jobId = String(message.jobId ?? "");
    const pending = this.pending.get(jobId);
    if (!pending) return;
    this.pending.delete(jobId);
    this.metrics.queueDepth = this.pending.size;
    if (message.kind !== "completed") {
      this.drop("TOKENIZER_EXCEPTION");
      return;
    }
    const queueDelayMs = performance.now() - pending.enqueuedAt;
    const tokenizerRuntimeMs = Number(message.tokenizerRuntimeMs ?? 0);
    const tokenCount = Number(message.tokenCount ?? 0);
    this.metrics.queueDelayMs.push(queueDelayMs);
    this.metrics.workerRuntimeMs.push(queueDelayMs);
    this.metrics.tokenizerRuntimeMs.push(tokenizerRuntimeMs);
    const result: AttributionResult = {
      context: pending.context,
      attemptId: pending.attemptId,
      attemptSequence: pending.attemptSequence,
      attemptType: pending.attemptType,
      tokenCount,
      serializedBytes: Number(message.serializedBytes ?? 0),
      queueDelayMs,
      tokenizerRuntimeMs,
      materiality: materialityForTokens(tokenCount),
      quality: "LOCALLY_CALCULATED",
    };
    const writeStarted = performance.now();
    try {
      const write = this.onResult(result);
      void Promise.resolve(write).then(
        () => {
          this.metrics.eventsCompleted += 1;
          this.metrics.databaseWriteRuntimeMs.push(performance.now() - writeStarted);
        },
        () => this.drop("WORKER_UNAVAILABLE"),
      );
    } catch {
      this.drop("WORKER_UNAVAILABLE");
    }
  }

  private drop(reason: AttributionDropReason): void {
    this.metrics.eventsDropped += 1;
    this.metrics.failOpenEvents += 1;
    this.metrics.errorsByReason[reason] = (this.metrics.errorsByReason[reason] ?? 0) + 1;
  }

  private failWorker(reason: AttributionDropReason): void {
    const lost = this.pending.size;
    this.pending.clear();
    this.metrics.queueDepth = 0;
    for (let i = 0; i < Math.max(1, lost); i += 1) this.drop(reason);
    this.worker = undefined;
  }

  async shutdown(): Promise<void> {
    this.shuttingDown = true;
    const lost = this.pending.size;
    this.pending.clear();
    this.metrics.queueDepth = 0;
    for (let i = 0; i < lost; i += 1) this.drop("SHUTTING_DOWN");
    if (this.worker) await this.worker.terminate();
    this.worker = undefined;
  }
}
