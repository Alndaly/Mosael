/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), loading: vi.fn() }),
}));

import { UpdateCheckButton } from "./LocalAppSection";

describe("应用内更新按钮", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    delete (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop;
  });

  it("检查 → 下载 → 下载完成 → 重启安装", async () => {
    const checkUpdates = vi.fn(async () => ({
      current: "2.2.1",
      latest: "2.2.2",
      hasUpdate: true,
      supportsAutoInstall: true,
      phase: "available",
      url: "https://github.com/Alndaly/Mosael/releases/tag/v2.2.2",
    }));
    const downloadUpdate = vi.fn(async () => ({
      latest: "2.2.2",
      hasUpdate: true,
      supportsAutoInstall: true,
      phase: "downloaded",
    }));
    const installUpdate = vi.fn(async () => ({ phase: "installing" }));
    (window as unknown as { mosaelDesktop: unknown }).mosaelDesktop = {
      checkUpdates,
      downloadUpdate,
      installUpdate,
      onUpdateAvailable: () => () => {},
      onUpdateProgress: () => () => {},
    };

    render(<UpdateCheckButton />);
    fireEvent.click(screen.getByRole("button", { name: "updateCheck" }));
    const download = await screen.findByRole("button", { name: "updateDownload" });
    // 刚查到的结果说支持安装时,toast 也必须直接给「下载并安装」,不能拿点击前的空状态判断。
    expect(toast).toHaveBeenCalledWith(
      "updateAvailable",
      expect.objectContaining({
        description: "updateDownloadHint",
        action: expect.objectContaining({ label: "updateDownload" }),
      }),
    );
    fireEvent.click(download);
    expect(downloadUpdate).toHaveBeenCalledTimes(1);

    const install = await screen.findByRole("button", { name: "updateInstallNow" });
    fireEvent.click(install);
    expect(installUpdate).toHaveBeenCalledTimes(1);
  });
});
