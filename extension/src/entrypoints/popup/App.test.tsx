import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const settings = vi.hoisted(() => ({
  checkLocalHealth: vi.fn(),
  getMode: vi.fn(),
  getApiUrl: vi.fn(),
  isBuiltInDisabledHost: vi.fn(),
  isDomainDisabled: vi.fn(),
  setDomainDisabled: vi.fn(),
}));
const components = vi.hoisted(() => ({ settingsProps: null as unknown }));

vi.mock("@/lib/settings", () => ({
  ...settings,
  normalizeHost: (host: string) => host.trim().toLowerCase().replace(/^www\./, ""),
}));
vi.mock("./components/AuthGate", () => ({ default: () => "auth-gate" }));
vi.mock("./components/SaveForm", () => ({ default: () => "save-ready" }));
vi.mock("./components/Settings", () => ({
  default: (props: unknown) => {
    components.settingsProps = props;
    return "settings";
  },
}));

import App from "./App";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
  .IS_REACT_ACT_ENVIRONMENT = true;

describe("popup startup lifecycle", () => {
  let container: HTMLDivElement;
  let root: Root | null;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    components.settingsProps = null;
    settings.getMode.mockResolvedValue("cloud");
    settings.getApiUrl.mockResolvedValue("https://api.example.test");
    settings.checkLocalHealth.mockResolvedValue(true);
    settings.isBuiltInDisabledHost.mockReturnValue(false);
    settings.isDomainDisabled.mockResolvedValue(false);
    settings.setDomainDisabled.mockResolvedValue(undefined);
    vi.stubGlobal("chrome", {
      tabs: { query: vi.fn(async () => []) },
      runtime: {
        sendMessage: vi.fn(async () => ({ accessToken: "token" })),
      },
    });
  });

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
      root = null;
    }
    container.remove();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("turns a stalled startup into a retryable state", async () => {
    settings.getMode
      .mockImplementationOnce(() => new Promise(() => {}))
      .mockResolvedValue("cloud");

    await act(async () => {
      root?.render(<App />);
      await Promise.resolve();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });

    expect(container.textContent).toContain("Extension startup timed out");
    const retry = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent === "Retry");
    expect(retry).toBeTruthy();

    await act(async () => {
      retry?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.textContent).toContain("save-ready");
    expect(settings.getMode).toHaveBeenCalledTimes(2);
  });

  it("invalidates a stalled startup when the popup unmounts", async () => {
    settings.getMode.mockImplementation(() => new Promise(() => {}));
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    await act(async () => {
      root?.render(<App />);
      await Promise.resolve();
    });
    await act(async () => root?.unmount());
    root = null;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });

    expect(consoleError).not.toHaveBeenCalled();
    expect(container.textContent).toBe("");
  });

  it("bounds a stalled API settings read during a mode transition", async () => {
    settings.getApiUrl
      .mockResolvedValueOnce("https://api.example.test")
      .mockImplementationOnce(() => new Promise(() => {}));

    await act(async () => {
      root?.render(<App />);
      await Promise.resolve();
      await Promise.resolve();
    });
    const settingsButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent === "Settings");
    await act(async () => {
      settingsButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const props = components.settingsProps as {
      onBack(): void;
      onModeChange(mode: "cloud" | "local"): Promise<void>;
    };
    let transition!: Promise<void>;
    await act(async () => {
      transition = props.onModeChange("cloud");
      await Promise.resolve();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
      await transition;
      props.onBack();
    });

    expect(container.textContent).toContain("API settings lookup timed out");
  });
});
