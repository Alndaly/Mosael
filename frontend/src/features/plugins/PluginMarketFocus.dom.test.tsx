/** @vitest-environment jsdom */
/**
 * 官网「在 Mosael 中打开」一个还没装的插件:市场打开后**直接弹出安装确认**(列出它要的权限),
 * 而不是让人在列表里再找、再点一次。装不装仍由确认卡上的按钮决定 —— 深链只导航,不执行。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  preview: vi.fn(async () => ({
    id: "dev.mosael.remotion", name: "Remotion 动画", version: "0.1.0", description: "用代码做动画",
    permissions: ["process:spawn"], tools: ["remotion_setup"], installed: false, installed_version: "",
    author_name: "Mosael", author_url: "", docs: "", homepage: "",
  })),
  install: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  listPluginMarket: async () => [
    { id: "dev.mosael.remotion", name: "Remotion 动画", version: "0.1.0", download: "https://x/remotion.zip",
      permissions: ["process:spawn"], installed: false, installed_version: "", author: "Mosael", author_url: "", docs: "", homepage: "", description: "" },
    { id: "dev.mosael.aws-s3", name: "Amazon S3", version: "0.1.2", download: "https://x/s3.zip",
      permissions: [], installed: false, installed_version: "", author: "Mosael", author_url: "", docs: "", homepage: "", description: "" },
  ],
  previewPluginInstall: mocks.preview,
  installPlugin: mocks.install,
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { PluginMarketDialog } from "@/features/plugins/PluginMarket";

it("没装的插件:直接弹出它的安装确认,但不替人按「安装」", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PluginMarketDialog open focusId="dev.mosael.remotion" onOpenChange={vi.fn()} onInstalled={vi.fn()} />
    </QueryClientProvider>,
  );

  expect(await screen.findByText("pluginInstallConfirmTitle")).toBeTruthy();
  expect(mocks.preview).toHaveBeenCalledTimes(1);
  expect(mocks.preview).toHaveBeenCalledWith("https://x/remotion.zip");
  await waitFor(() => expect(mocks.install).not.toHaveBeenCalled());
});
