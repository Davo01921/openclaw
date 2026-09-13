import { parentPort } from "node:worker_threads";
import { getEncoding } from "js-tiktoken";

const encoder = getEncoding("o200k_base");

parentPort.on("message", (message) => {
  const started = performance.now();
  try {
    let serialized = message.request;
    const tokenCount = encoder.encode(serialized).length;
    const serializedBytes = Buffer.byteLength(serialized, "utf8");
    serialized = "";
    parentPort.postMessage({
      kind: "completed",
      jobId: message.jobId,
      tokenCount,
      serializedBytes,
      tokenizerRuntimeMs: performance.now() - started,
    });
  } catch {
    parentPort.postMessage({ kind: "failed", jobId: message.jobId });
  }
});
