/** Request-scoped, disabled-by-default observation at the provider egress boundary. */

export type ProviderRequestIdentity = Readonly<{
  agentId?: string;
  sessionId?: string;
  runId?: string;
  taskId?: string;
  modelCallId?: string;
  traceId?: string;
}>;

export type ProviderRequestReadyContext = ProviderRequestIdentity &
  Readonly<{
    provider: string;
    model: string;
    egress: string;
    payloadVariant?: string;
  }>;

export type DeepReadonly<T> = T extends (...args: never[]) => unknown
  ? T
  : T extends readonly (infer U)[]
    ? readonly DeepReadonly<U>[]
    : T extends object
      ? { readonly [K in keyof T]: DeepReadonly<T[K]> }
      : T;

export type ProviderRequestReadyFailure = Readonly<{
  kind: "observer_exception" | "observer_rejection" | "observer_timeout";
}>;

export type ProviderRequestReadyRegistration = Readonly<{
  identity: ProviderRequestIdentity;
  allowedAgentIds: readonly string[];
  observer: (
    context: ProviderRequestReadyContext,
    request: DeepReadonly<unknown>,
  ) => void | Promise<void>;
  onFailure?: (failure: ProviderRequestReadyFailure) => void;
  timeoutMs?: number;
}>;

const PROVIDER_REQUEST_READY_OBSERVER = Symbol("providerRequestReadyObserver");

function readonlyView<T extends object>(value: T): DeepReadonly<T> {
  const cache = new WeakMap<object, object>();
  const wrap = (candidate: unknown): unknown => {
    if ((typeof candidate !== "object" && typeof candidate !== "function") || candidate === null) {
      return candidate;
    }
    const object = candidate as object;
    const cached = cache.get(object);
    if (cached) {
      return cached;
    }
    const proxy = new Proxy(object, {
      get(target, property, receiver) {
        return wrap(Reflect.get(target, property, receiver));
      },
      set: () => false,
      deleteProperty: () => false,
      defineProperty: () => false,
      setPrototypeOf: () => false,
      preventExtensions: () => false,
    });
    cache.set(object, proxy);
    return proxy;
  };
  return wrap(value) as DeepReadonly<T>;
}

function reportFailure(
  registration: ProviderRequestReadyRegistration,
  failure: ProviderRequestReadyFailure,
): void {
  try {
    registration.onFailure?.(failure);
  } catch {
    // Observability must never affect provider execution.
  }
}

export const providerRequestReadyObserver = {
  set(options: object, registration: ProviderRequestReadyRegistration): void {
    Reflect.set(options, PROVIDER_REQUEST_READY_OBSERVER, registration);
  },
  get(options: object | undefined): ProviderRequestReadyRegistration | undefined {
    if (!options) {
      return undefined;
    }
    const value: unknown = Reflect.get(options, PROVIDER_REQUEST_READY_OBSERVER);
    return value && typeof value === "object"
      ? (value as ProviderRequestReadyRegistration)
      : undefined;
  },
  copy(source: object | undefined, target: object): void {
    const registration = providerRequestReadyObserver.get(source);
    if (registration) {
      providerRequestReadyObserver.set(target, registration);
    }
  },
};

/**
 * Creates an egress callback only for an explicitly registered and authorized request.
 * The callback never awaits observer work and never throws into provider execution.
 */
export function createProviderRequestReadyObserver(params: {
  options: object | undefined;
  provider: string;
  model: string;
  egress: string;
}) {
  const registration = providerRequestReadyObserver.get(params.options);
  const agentId = registration?.identity.agentId;
  if (!registration || !agentId || !registration.allowedAgentIds.includes(agentId)) {
    return undefined;
  }
  const contextBase = Object.freeze({
    ...registration.identity,
    provider: params.provider,
    model: params.model,
    egress: params.egress,
  });
  return (request: object, metadata?: { payloadVariant?: string }): void => {
    const context = Object.freeze({ ...contextBase, ...metadata });
    let result: void | Promise<void>;
    try {
      result = registration.observer(context, readonlyView(request));
    } catch {
      reportFailure(registration, { kind: "observer_exception" });
      return;
    }
    if (!result || typeof (result as Promise<void>).then !== "function") {
      return;
    }
    let settled = false;
    const timeoutMs = Math.max(1, registration.timeoutMs ?? 1_000);
    const timer = setTimeout(() => {
      if (!settled) {
        reportFailure(registration, { kind: "observer_timeout" });
      }
    }, timeoutMs);
    timer.unref?.();
    void result.then(
      () => {
        settled = true;
        clearTimeout(timer);
      },
      () => {
        settled = true;
        clearTimeout(timer);
        reportFailure(registration, { kind: "observer_rejection" });
      },
    );
  };
}
