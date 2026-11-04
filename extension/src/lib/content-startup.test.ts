import { describe, expect, it, vi } from "vitest";

import {
  ensureContentStarted,
  type ContentStartupDependencies,
  type ContentStartupState,
} from "./content-startup";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

describe("ensureContentStarted", () => {
  it("installs one in-flight sentinel before concurrent eligibility work starts", async () => {
    const state: ContentStartupState<object> = {};
    const eligibility = deferred<boolean>();
    const boot = deferred<void>();
    const controller = {};
    const dependencies: ContentStartupDependencies<object> = {
      isEligible: vi.fn(() => eligibility.promise),
      createController: vi.fn(() => controller),
      bootstrap: vi.fn(() => boot.promise),
      dispose: vi.fn(),
    };

    const first = ensureContentStarted(state, dependencies);
    const second = ensureContentStarted(state, dependencies);

    expect(second).toBe(first);
    expect(state.__llmwikiInitPromise).toBe(first);
    expect(dependencies.isEligible).not.toHaveBeenCalled();

    await Promise.resolve();
    eligibility.resolve(true);
    await vi.waitFor(() => {
      expect(dependencies.createController).toHaveBeenCalledOnce();
    });
    expect(state.__llmwikiLoaded).not.toBe(true);

    boot.resolve();
    await first;
    expect(state.__llmwikiLoaded).toBe(true);
    expect(state.__llmwikiController).toBe(controller);
    expect(state.__llmwikiInitPromise).toBeUndefined();
  });

  it("clears failed and ineligible attempts so a later injection can retry", async () => {
    const state: ContentStartupState<object> = {};
    const dependencies: ContentStartupDependencies<object> = {
      isEligible: vi.fn()
        .mockResolvedValueOnce(false)
        .mockResolvedValue(true),
      createController: vi.fn(() => ({})),
      bootstrap: vi.fn()
        .mockRejectedValueOnce(new Error("storage failed"))
        .mockResolvedValue(undefined),
      dispose: vi.fn(),
    };

    await ensureContentStarted(state, dependencies);
    expect(state.__llmwikiLoaded).not.toBe(true);
    expect(state.__llmwikiInitPromise).toBeUndefined();

    await expect(ensureContentStarted(state, dependencies)).rejects.toThrow("storage failed");
    expect(dependencies.dispose).toHaveBeenCalledOnce();
    expect(state.__llmwikiLoaded).not.toBe(true);
    expect(state.__llmwikiInitPromise).toBeUndefined();

    await ensureContentStarted(state, dependencies);
    expect(state.__llmwikiLoaded).toBe(true);
    expect(dependencies.createController).toHaveBeenCalledTimes(2);
  });

  it("bounds a bootstrap that never settles and leaves startup retryable", async () => {
    vi.useFakeTimers();
    const state: ContentStartupState<object> = {};
    const controller = {};
    const dependencies: ContentStartupDependencies<object> = {
      isEligible: vi.fn(async () => true),
      createController: vi.fn(() => controller),
      bootstrap: vi.fn(() => new Promise<void>(() => {})),
      dispose: vi.fn(),
      bootstrapTimeoutMs: 25,
    };
    try {
      const result = ensureContentStarted(state, dependencies);
      const expectation = expect(result).rejects.toThrow("Content-script bootstrap timed out");
      await vi.advanceTimersByTimeAsync(25);
      await expectation;

      expect(dependencies.dispose).toHaveBeenCalledWith(controller);
      expect(state.__llmwikiLoaded).not.toBe(true);
      expect(state.__llmwikiInitPromise).toBeUndefined();
    } finally {
      vi.useRealTimers();
    }
  });

  it("bounds a storage-backed eligibility check before creating a controller", async () => {
    vi.useFakeTimers();
    const state: ContentStartupState<object> = {};
    const dependencies: ContentStartupDependencies<object> = {
      isEligible: vi.fn(() => new Promise<boolean>(() => {})),
      createController: vi.fn(() => ({})),
      bootstrap: vi.fn(async () => undefined),
      dispose: vi.fn(),
      eligibilityTimeoutMs: 15,
    };
    try {
      const result = ensureContentStarted(state, dependencies);
      const expectation = expect(result).rejects.toThrow(
        "Content-script eligibility check timed out",
      );
      await vi.advanceTimersByTimeAsync(15);
      await expectation;

      expect(dependencies.createController).not.toHaveBeenCalled();
      expect(state.__llmwikiInitPromise).toBeUndefined();
      expect(state.__llmwikiLoaded).not.toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});
