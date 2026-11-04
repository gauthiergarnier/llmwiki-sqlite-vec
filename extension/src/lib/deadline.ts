export class DeadlineError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DeadlineError";
  }
}

export const API_READ_TIMEOUT_MS = 20_000;
export const API_WRITE_TIMEOUT_MS = 120_000;
export const PDF_UPLOAD_TIMEOUT_MS = 10 * 60_000;
export const AUTH_REQUEST_TIMEOUT_MS = 15_000;
export const RUNTIME_MESSAGE_TIMEOUT_MS = 5_000;

export function withDeadline<T>(
  promise: PromiseLike<T>,
  timeoutMs: number,
  message = "Operation timed out",
  onTimeout?: () => void,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const timer = globalThis.setTimeout(() => {
      if (settled) return;
      settled = true;
      onTimeout?.();
      reject(new DeadlineError(message));
    }, timeoutMs);

    Promise.resolve(promise).then(
      (value) => {
        if (settled) return;
        settled = true;
        globalThis.clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        if (settled) return;
        settled = true;
        globalThis.clearTimeout(timer);
        reject(error);
      },
    );
  });
}

export async function runWithDeadline<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  timeoutMs: number,
  message = "Operation timed out",
  externalSignal?: AbortSignal | null,
): Promise<T> {
  const controller = new AbortController();
  const abortFromCaller = () => controller.abort(externalSignal?.reason);

  if (externalSignal?.aborted) {
    controller.abort(externalSignal.reason);
  } else {
    externalSignal?.addEventListener("abort", abortFromCaller, { once: true });
  }

  try {
    return await withDeadline(
      Promise.resolve().then(() => operation(controller.signal)),
      timeoutMs,
      message,
      () => controller.abort(new DOMException(message, "TimeoutError")),
    );
  } finally {
    externalSignal?.removeEventListener("abort", abortFromCaller);
  }
}

export function runtimeMessageWithDeadline<T = unknown>(
  message: unknown,
  timeoutMs = RUNTIME_MESSAGE_TIMEOUT_MS,
  timeoutMessage = "The extension background did not respond",
): Promise<T> {
  return withDeadline(
    chrome.runtime.sendMessage(message) as Promise<T>,
    timeoutMs,
    timeoutMessage,
  );
}

export function tabMessageWithDeadline<T = unknown>(
  tabId: number,
  message: unknown,
  timeoutMs = RUNTIME_MESSAGE_TIMEOUT_MS,
  timeoutMessage = "The page did not respond to the extension",
): Promise<T> {
  return withDeadline(
    chrome.tabs.sendMessage(tabId, message) as Promise<T>,
    timeoutMs,
    timeoutMessage,
  );
}
