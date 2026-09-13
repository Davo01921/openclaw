import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { appendFile, writeFile } from "node:fs/promises";
import path from "node:path";
import {
  ProviderAttributionQueue,
  providerRequestReadyObserver,
  type AttributionResult,
} from "@openclaw/ai/transports";
import type { StreamFn } from "./runtime/index.js";

const ENABLED = process.env.OPENCLAW_FRED_ATTRIBUTION_CANARY === "1";
const KILLED = process.env.OPENCLAW_FRED_ATTRIBUTION_KILL_SWITCH === "1";
const ROOT = process.env.OPENCLAW_FRED_ATTRIBUTION_DIR?.trim();
const DEADLINE = Number(process.env.OPENCLAW_FRED_ATTRIBUTION_DEADLINE_MS ?? 0);
const ALLOWED_AGENT_IDS = ["fred"] as const;

type CanaryState = {
  version: 1;
  startedAtMs: number;
  deadlineMs: number;
  eligibleCalls: number;
  observedCalls: number;
  completedJobs: number;
  stoppedAtMs?: number;
  stopReason?: string;
};

let state: CanaryState | undefined;
let writeChain = Promise.resolve();
const callSequenceByRun = new Map<string, number>();

function freshEpochState(): CanaryState {
  return {
    version: 1,
    startedAtMs: Date.now(),
    deadlineMs: DEADLINE || 0,
    eligibleCalls: 0,
    observedCalls: 0,
    completedJobs: 0,
  };
}

function ensureStateSync(): void {
  if (state || !ROOT) return;
  mkdirSync(ROOT, { recursive: true });
  try {
    const disk = JSON.parse(readFileSync(path.join(ROOT, "state.json"), "utf8")) as CanaryState;
    state = (disk.deadlineMs ?? 0) === (DEADLINE || 0) ? disk : freshEpochState();
  } catch {
    state = freshEpochState();
  }
  void enqueueWrite(persistState);
}

async function persistState(): Promise<void> {
  if (!ROOT || !state) return;
  try {
    const disk = JSON.parse(readFileSync(path.join(ROOT, "state.json"), "utf8")) as CanaryState;
    if (
      disk &&
      typeof disk.eligibleCalls === "number" &&
      (disk.deadlineMs ?? 0) === (state.deadlineMs ?? 0)
    ) {
      state = {
        ...state,
        eligibleCalls: Math.max(disk.eligibleCalls, state.eligibleCalls),
        observedCalls: Math.max(disk.observedCalls ?? 0, state.observedCalls ?? 0),
        completedJobs: Math.max(disk.completedJobs ?? 0, state.completedJobs ?? 0),
        deadlineMs: disk.deadlineMs || state.deadlineMs,
        stoppedAtMs: disk.stoppedAtMs ?? state.stoppedAtMs,
        stopReason: disk.stopReason ?? state.stopReason,
      };
    }
  } catch {
    // A missing or temporarily unreadable state file starts from in-memory state.
  }
  await writeFile(path.join(ROOT, "state.json"), `${JSON.stringify(state)}\n`, { mode: 0o600 });
}

function enqueueWrite(operation: () => Promise<void>): Promise<void> {
  writeChain = writeChain.then(operation, operation).catch(() => undefined);
  return writeChain;
}

function stop(reason: string): void {
  if (!state || state.stoppedAtMs) return;
  state.stoppedAtMs = Date.now();
  state.stopReason = reason;
  void enqueueWrite(persistState);
  void queue.shutdown();
}

async function storeResult(result: AttributionResult): Promise<void> {
  if (!ROOT || !state || state.stoppedAtMs) return;
  const row = {
    schemaVersion: 1,
    observedAtMs: Date.now(),
    ...result.context,
    attemptId: result.attemptId,
    attemptSequence: result.attemptSequence,
    attemptType: result.attemptType,
    tokenCount: result.tokenCount,
    serializedBytes: result.serializedBytes,
    queueDelayMs: result.queueDelayMs,
    tokenizerRuntimeMs: result.tokenizerRuntimeMs,
    materiality: result.materiality,
    quality: result.quality,
  };
  const started = performance.now();
  await appendFile(path.join(ROOT, "events.jsonl"), `${JSON.stringify(row)}\n`, { mode: 0o600 });
  queue.metrics.databaseWriteRuntimeMs.push(performance.now() - started);
  state.completedJobs += 1;
  await enqueueWrite(persistState);
}

const queue = new ProviderAttributionQueue(
  {
    enabled: ENABLED && Boolean(ROOT),
    killSwitch: KILLED,
    allowedAgentIds: ALLOWED_AGENT_IDS,
    maxInFlight: 4,
    maxSeenAttempts: 4_096,
  },
  storeResult,
);

if (ENABLED) {
  console.log(
    `[fred-attribution-canary] observer module loaded agent=fred deadline=${DEADLINE || "unset"} root=${ROOT ?? "unset"}`,
  );
}

export function wrapStreamFnWithFredAttributionCanary(params: {
  streamFn: StreamFn;
  agentId: string;
  sessionId: string;
  runId: string;
  taskId?: string;
}): StreamFn {
  if (!ENABLED || KILLED || !ROOT || params.agentId !== "fred") return params.streamFn;
  ensureStateSync();
  return (model, context, options = {}) => {
    const now = Date.now();
    if (existsSync(path.join(ROOT, "KILL"))) {
      stop("MANUAL_KILL_SWITCH");
      return params.streamFn(model, context, options);
    }
    if (!state || state.stoppedAtMs || (state.deadlineMs > 0 && now >= state.deadlineMs)) {
      if (state && !state.stoppedAtMs && state.deadlineMs > 0 && now >= state.deadlineMs) {
        stop("DEADLINE");
      }
      return params.streamFn(model, context, options);
    }
    state.eligibleCalls += 1;
    void enqueueWrite(persistState);
    const callSequence = (callSequenceByRun.get(params.runId) ?? 0) + 1;
    callSequenceByRun.set(params.runId, callSequence);
    const modelCallId = `${params.runId}:${callSequence}`;
    installFredAttributionRegistration(options, {
      agentId: params.agentId,
      sessionId: params.sessionId,
      runId: params.runId,
      taskId: params.taskId,
      modelCallId,
    });
    return params.streamFn(model, context, options);
  };
}

function installFredAttributionRegistration(
  options: object,
  ids: {
    agentId: string;
    sessionId: string;
    runId: string;
    taskId?: string;
    modelCallId: string;
  },
): void {
  let attemptSequence = 0;
  providerRequestReadyObserver.set(options, {
    identity: { ...ids, traceId: ids.modelCallId },
    allowedAgentIds: ALLOWED_AGENT_IDS,
    observer: (requestContext, request) => {
      attemptSequence += 1;
      const accepted = queue.observe(requestContext, request as object, attemptSequence);
      if (accepted && state) {
        state.observedCalls += 1;
        void enqueueWrite(persistState);
      }
    },
    onFailure: () => {
      queue.metrics.failOpenEvents += 1;
    },
  });
}

/** Re-register after the inference envelope's structured-clone boundary. */
export function registerFredAttributionOnInferenceOptions(
  options: object,
  ids: { agentId: string; sessionId: string; runId: string; modelCallId: string },
): void {
  if (!ENABLED || KILLED || !ROOT || ids.agentId !== "fred") return;
  ensureStateSync();
  const now = Date.now();
  if (existsSync(path.join(ROOT, "KILL"))) {
    stop("MANUAL_KILL_SWITCH");
    return;
  }
  if (!state || state.stoppedAtMs || (state.deadlineMs > 0 && now >= state.deadlineMs)) {
    if (state && !state.stoppedAtMs && state.deadlineMs > 0 && now >= state.deadlineMs) {
      stop("DEADLINE");
    }
    return;
  }
  installFredAttributionRegistration(options, ids);
}

export function fredAttributionCanarySnapshot() {
  return { enabled: ENABLED, killed: KILLED, root: ROOT, state, metrics: queue.metrics };
}
