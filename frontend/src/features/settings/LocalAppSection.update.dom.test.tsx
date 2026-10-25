/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

import { UpdateCheckButton } from "./LocalAppSection";

describe("应用内更新按钮", () => {
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
    fireEvent.click(download);
    expect(downloadUpdate).toHaveBeenCalledTimes(1);

    const install = await screen.findByRole("button", { name: "updateInstallNow" });
    fireEvent.click(install);
    expect(installUpdate).toHaveBeenCalledTimes(1);
  });
});
