import { describe, expect, it, vi } from "vitest";

import { DeadlineError, runWithDeadline, withDeadline } from "./deadline";

describe("deadline helpers", () => {
  it("rejects a never-settling promise", async () => {
    vi.useFakeTimers();
    try {
      const result = withDeadline(new Promise<never>(() => {}), 25, "Background stalled");
      const expectation = expect(result).rejects.toEqual(
        expect.objectContaining({ name: "DeadlineError", message: "Background stalled" }),
      );
      await vi.advanceTimersByTimeAsync(25);
      await expectation;
    } finally {
      vi.useRealTimers();
    }
  });

  it("aborts a timed operation even when its promise ignores the signal", async () => {
    vi.useFakeTimers();
    const sawAbort = vi.fn();
    try {
      const result = runWithDeadline(
        (signal) => {
          signal.addEventListener("abort", sawAbort, { once: true });
          return new Promise<never>(() => {});
        },
        10,
        "Fetch timed out",
      );
      const expectation = expect(result).rejects.toBeInstanceOf(DeadlineError);
      await vi.advanceTimersByTimeAsync(10);
      await expectation;
      expect(sawAbort).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });
});
