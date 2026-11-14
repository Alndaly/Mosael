/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import type { MessageKey } from "@/app/messages";
import { announceUpdate, showUpdateProgress } from "./updateNotice";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), loading: vi.fn() }),
}));

const t = (key: MessageKey) => key;
const installed = {
  current: "2.6.2",
  latest: "2.6.3",
  hasUpdate: true,
  supportsAutoInstall: true,
  phase: "available" as const,
  url: "https://github.com/Alndaly/Mosael/releases/tag/v2.6.3",
};

function bridge(extra: Record<string, unknown> = {}) {
  Object.defineProperty(window, "mosaelDesktop", {
    configurable: true,
    value: {
      downloadUpdate: vi.fn(async () => ({ ...installed, phase: "downloaded" })),
      installUpdate: vi.fn(async () => ({ ...installed, phase: "installing" })),
      ...extra,
    },
  });
  return window.mosaelDesktop!;
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  delete (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop;
  vi.restoreAllMocks();
});

describe("应用内更新提示", () => {
  it("安装版直接给下载安装,不把用户送去网页", () => {
    const desktop = bridge();
    announceUpdate(t, installed);
    const options = vi.mocked(toast).mock.calls[0]?.[1] as {
      description: string;
      action: { label: string; onClick: () => void };
    };
    expect(options.description).toBe("updateDownloadHint");
    expect(options.action.label).toBe("updateDownload");
    options.action.onClick();
    expect(desktop.downloadUpdate).toHaveBeenCalledTimes(1);
  });

  it("开发版明确说不能应用内更新,动作是打开发布页", () => {
    bridge();
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    announceUpdate(t, { ...installed, supportsAutoInstall: false });
    const options = vi.mocked(toast).mock.calls[0]?.[1] as {
      description: string;
      action: { label: string; onClick: () => void };
    };
    expect(options.description).toBe("updateUnsupportedHint");
    expect(options.action.label).toBe("updateOpenRelease");
    options.action.onClick();
    expect(open).toHaveBeenCalledWith(installed.url, "_blank");
  });

  it("下载完成后的提示直接给重启安装", () => {
    const desktop = bridge();
    showUpdateProgress(t, { ...installed, phase: "downloaded" });
    const options = vi.mocked(toast.success).mock.calls[0]?.[1] as {
      action: { label: string; onClick: () => void };
    };
    expect(options.action.label).toBe("updateInstallNow");
    options.action.onClick();
    expect(desktop.installUpdate).toHaveBeenCalledTimes(1);
  });
});
