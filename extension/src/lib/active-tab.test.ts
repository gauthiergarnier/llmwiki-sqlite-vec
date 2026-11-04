import { describe, expect, it, vi } from "vitest";

import { detectActivePage } from "./active-tab";

describe("detectActivePage", () => {
  it("returns a recoverable state when Chrome exposes no active URL", async () => {
    const result = await detectActivePage({
      queryActiveTab: vi.fn(async () => ({ id: 7 })),
      detectPdf: vi.fn(async () => false),
    });

    expect(result).toEqual({
      status: "unavailable",
      message: expect.stringContaining("active page is unavailable"),
    });
  });

  it("returns a recoverable state when tab inspection rejects", async () => {
    const result = await detectActivePage({
      queryActiveTab: vi.fn(async () => {
        throw new Error("Extension context invalidated");
      }),
      detectPdf: vi.fn(async () => false),
    });

    expect(result).toEqual({
      status: "unavailable",
      message: expect.stringContaining("Extension context invalidated"),
    });
  });

  it("returns a recoverable state when tab inspection never settles", async () => {
    vi.useFakeTimers();
    try {
      const result = detectActivePage({
        queryActiveTab: vi.fn(() => new Promise<never>(() => {})),
        detectPdf: vi.fn(async () => false),
      });
      const expectation = expect(result).resolves.toEqual({
        status: "unavailable",
        message: expect.stringContaining("Timed out while inspecting"),
      });

      await vi.advanceTimersByTimeAsync(5_000);
      await expectation;
    } finally {
      vi.useRealTimers();
    }
  });

  it("returns normalized tab information for an ordinary web page", async () => {
    const result = await detectActivePage({
      queryActiveTab: vi.fn(async () => ({
        id: 9,
        url: "https://example.com/article",
        title: "Article",
      })),
      detectPdf: vi.fn(async () => false),
    });

    expect(result).toEqual({
      status: "ready",
      tab: {
        tabId: 9,
        url: "https://example.com/article",
        title: "Article",
        isPdf: false,
      },
    });
  });
});
