import { isPdfTab } from "./pdf";
import { RUNTIME_MESSAGE_TIMEOUT_MS, withDeadline } from "./deadline";

export interface ActivePageTab {
  url: string;
  title: string;
  isPdf: boolean;
  tabId: number;
}

export type ActivePageResult =
  | { status: "ready"; tab: ActivePageTab }
  | { status: "unavailable"; message: string };

export interface ActivePageDependencies {
  queryActiveTab(): Promise<Pick<chrome.tabs.Tab, "id" | "url" | "title"> | undefined>;
  detectPdf(tabId: number, url: string, title: string | undefined): Promise<boolean>;
}

const defaultDependencies: ActivePageDependencies = {
  queryActiveTab: async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    return tab;
  },
  detectPdf: isPdfTab,
};

export async function detectActivePage(
  dependencies: ActivePageDependencies = defaultDependencies,
): Promise<ActivePageResult> {
  try {
    const activeTab = await withDeadline(
      dependencies.queryActiveTab(),
      RUNTIME_MESSAGE_TIMEOUT_MS,
      "Timed out while inspecting the active page",
    );
    if (!activeTab?.url || activeTab.id == null) {
      return {
        status: "unavailable",
        message: "The active page is unavailable. Switch to a web page and try again.",
      };
    }

    let protocol = "";
    try {
      protocol = new URL(activeTab.url).protocol;
    } catch {
      // Invalid and browser-internal URLs are handled as unsupported below.
    }
    if (protocol !== "http:" && protocol !== "https:") {
      return {
        status: "unavailable",
        message: "This browser page cannot be saved. Open an http(s) page and try again.",
      };
    }

    const title = activeTab.title ?? "";
    const isPdf = await dependencies.detectPdf(activeTab.id, activeTab.url, title);
    return {
      status: "ready",
      tab: { url: activeTab.url, title, isPdf, tabId: activeTab.id },
    };
  } catch (error) {
    return {
      status: "unavailable",
      message: error instanceof Error
        ? `Could not inspect the active page: ${error.message}`
        : "Could not inspect the active page.",
    };
  }
}
