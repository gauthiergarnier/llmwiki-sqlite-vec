import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  detectActivePage: vi.fn(),
  fetchKnowledgeBases: vi.fn(),
  getDocumentByUrl: vi.fn(),
  getSelectedFolderPath: vi.fn(),
  getSelectedKnowledgeBaseId: vi.fn(),
  setSelectedFolderPath: vi.fn(),
  setSelectedKnowledgeBaseId: vi.fn(),
}));

vi.mock("@/lib/active-tab", () => ({ detectActivePage: mocks.detectActivePage }));
vi.mock("@/lib/api", () => ({
  createKnowledgeBase: vi.fn(),
  fetchKnowledgeBases: mocks.fetchKnowledgeBases,
  getDocumentByUrl: mocks.getDocumentByUrl,
  moveDocument: vi.fn(),
  saveWebPage: vi.fn(),
}));
vi.mock("@/lib/settings", () => ({
  getSelectedFolderPath: mocks.getSelectedFolderPath,
  getSelectedKnowledgeBaseId: mocks.getSelectedKnowledgeBaseId,
  normalizeFolderPath: (path: string) => path,
  setSelectedFolderPath: mocks.setSelectedFolderPath,
  setSelectedKnowledgeBaseId: mocks.setSelectedKnowledgeBaseId,
}));
vi.mock("@/lib/pdf", () => ({ normalizePdfSourceUrl: (url: string) => url }));
vi.mock("@/lib/pdf-save-jobs", () => ({ runPdfSaveJob: vi.fn() }));
vi.mock("@/lib/page-capture", () => ({ capturePageHtml: () => "<html></html>" }));
vi.mock("@/lib/url", () => ({ canonicalize: (url: string) => url }));

import SaveForm, { SAVED_DESTINATION_TIMEOUT_MS } from "./SaveForm";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
  .IS_REACT_ACT_ENVIRONMENT = true;

const knowledgeBases = [
  { id: "first", name: "First" },
  { id: "saved", name: "Saved" },
];

describe("SaveForm saved destination lifecycle", () => {
  let container: HTMLDivElement;
  let root: Root | null;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    mocks.detectActivePage.mockResolvedValue({
      status: "ready",
      tab: {
        tabId: 7,
        url: "https://example.com/article",
        title: "Article",
        isPdf: false,
      },
    });
    mocks.fetchKnowledgeBases.mockResolvedValue(knowledgeBases);
    mocks.getDocumentByUrl.mockResolvedValue(null);
    mocks.setSelectedFolderPath.mockResolvedValue(undefined);
    mocks.setSelectedKnowledgeBaseId.mockResolvedValue(undefined);
    vi.stubGlobal("chrome", {
      scripting: { executeScript: vi.fn(async () => []) },
      tabs: { sendMessage: vi.fn(async () => ({ highlights: [] })) },
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

  it("falls back after stalled preference reads so saving becomes available", async () => {
    mocks.getSelectedKnowledgeBaseId.mockImplementation(() => new Promise(() => {}));
    mocks.getSelectedFolderPath.mockImplementation(() => new Promise(() => {}));

    await act(async () => {
      root?.render(<SaveForm apiUrl="https://api.example.test" accessToken="token" />);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.textContent).toContain("Loading saved destination");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(SAVED_DESTINATION_TIMEOUT_MS);
      await Promise.resolve();
      await Promise.resolve();
    });

    const select = container.querySelector("select") as HTMLSelectElement | null;
    const save = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent === "Save to LLM Wiki");
    expect(select?.value).toBe("first");
    expect(save?.disabled).toBe(false);
  });

  it("mounts the picker with the persisted KB instead of racing to the first KB", async () => {
    mocks.getSelectedKnowledgeBaseId.mockResolvedValue("saved");
    mocks.getSelectedFolderPath.mockResolvedValue("/research/");

    await act(async () => {
      root?.render(<SaveForm apiUrl="https://api.example.test" accessToken="token" />);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    const select = container.querySelector("select") as HTMLSelectElement | null;
    expect(select?.value).toBe("saved");
    expect(mocks.setSelectedKnowledgeBaseId).not.toHaveBeenCalledWith("first");
  });

  it("does not update state when preference deadlines fire after unmount", async () => {
    mocks.getSelectedKnowledgeBaseId.mockImplementation(() => new Promise(() => {}));
    mocks.getSelectedFolderPath.mockImplementation(() => new Promise(() => {}));
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    await act(async () => {
      root?.render(<SaveForm apiUrl="https://api.example.test" accessToken="token" />);
      await Promise.resolve();
    });
    await act(async () => root?.unmount());
    root = null;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SAVED_DESTINATION_TIMEOUT_MS);
    });

    expect(consoleError).not.toHaveBeenCalled();
  });
});
