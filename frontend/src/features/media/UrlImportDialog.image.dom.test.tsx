/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 「从链接导入」里的图片直链入口。
 *
 * 分析里说现在只能走内嵌浏览器采集 —— 贴一张图进来没有地方可去。这个入口就加在素材库
 * 那个对话框里(不另开一套):复用截图那条路的闸,失败时也在这里指过去。
 */

const mocks = vi.hoisted(() => ({
  importImageUrl: vi.fn(),
  probeUrl: vi.fn(),
  importFromUrl: vi.fn(),
  listBrowserProfiles: vi.fn(async () => []),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

vi.mock("sonner", () => ({ toast: { success: mocks.toastSuccess, error: mocks.toastError } }));

vi.mock("@/api/client", async (original) => {
  const actual = await original<typeof import("@/api/client")>();
  return {
    ...actual,
    listBrowserProfiles: mocks.listBrowserProfiles,
    probeUrl: mocks.probeUrl,
    importFromUrl: mocks.importFromUrl,
  };
});

vi.mock("@/features/media/importImageUrl", () => ({ importImageUrl: mocks.importImageUrl }));

import { UrlImportDialog } from "@/features/media/UrlImportDialog";

function renderDialog() {
  const onOpenChange = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <UrlImportDialog
        open
        onOpenChange={onOpenChange}
        workspace={{ id: "w1", name: "W" } as never}
        projectId={null}
      />
    </QueryClientProvider>,
  );
  return { onOpenChange };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.listBrowserProfiles.mockResolvedValue([]);
});

describe("从链接导入 · 图片直链", () => {
  it("贴一张图:直接调图片导入接口,成功后关掉对话框", async () => {
    const user = userEvent.setup();
    mocks.importImageUrl.mockResolvedValue({ id: "asset-1" });
    const { onOpenChange } = renderDialog();

    await user.type(
      screen.getByLabelText("urlImportImageLabel"),
      "https://cdn.example.com/cover.png",
    );
    await user.click(screen.getByRole("button", { name: /urlImportImageStart/ }));

    await waitFor(() =>
      expect(mocks.importImageUrl).toHaveBeenCalledWith({
        workspace_id: "w1",
        project_id: null,
        url: "https://cdn.example.com/cover.png",
      }),
    );
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    // 视频那条路没有被误触发。
    expect(mocks.probeUrl).not.toHaveBeenCalled();
    expect(mocks.importFromUrl).not.toHaveBeenCalled();
  });

  it("视频链接取不到时,失败卡里指向图片直链", async () => {
    const user = userEvent.setup();
    mocks.probeUrl.mockRejectedValue(new Error("This site isn't supported."));
    renderDialog();

    await user.type(screen.getByLabelText("urlImportLinkLabel"), "https://example.com/watch");
    await user.click(screen.getByRole("button", { name: "urlImportProbe" }));

    expect(await screen.findByText("This site isn't supported.")).toBeInTheDocument();
    expect(screen.getByText("urlImportTryDirect")).toBeInTheDocument();
    expect(document.querySelector("[data-failure='']")).not.toBeNull();
    // 原话也仍然弹一次 toast(不改变既有行为)。
    expect(mocks.toastError).toHaveBeenCalled();
  });
});
