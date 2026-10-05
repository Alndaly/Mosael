/** @vitest-environment jsdom */
/**
 * 工具结果里交回的图和视频看大图:同一次调用交回的那一批装进一个画廊,图点一下就开,视频由播放器的「全屏」开
 * 同一个灯箱(此前视频那颗走的是浏览器原生全屏,翻不到同一批里的图)。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("@/api/transport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/transport")>()),
  api: async (path: string) => {
    const id = path.split("/").pop() ?? "";
    return { id, name: `素材 ${id}`, kind: id.startsWith("vid") ? "video" : "image", workspace_id: "w" };
  },
}));
const openImagePreview = vi.hoisted(() => vi.fn());
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview, isImagePreviewOpen: false }) }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { assetFileUrl, assetPreviewUrl } from "@/api/client";
import { ToolCalls } from "@/features/agent/ToolCalls";

afterEach(() => {
  cleanup();
  openImagePreview.mockReset();
});

function renderResult() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ToolCalls tools={[{ id: "t1", name: "run_plugin_tool", status: "done", args: {}, result: { asset_ids: ["img-1", "vid-1"] } }]} />
    </QueryClientProvider>,
  );
}

const batch = [
  { src: assetPreviewUrl("img-1"), title: "素材 img-1", video: false },
  { src: assetFileUrl("vid-1"), title: "素材 vid-1", video: true },
];

it("视频的「全屏」开同一个灯箱,和同一批的图一起翻", async () => {
  renderResult();
  fireEvent.click(await screen.findByRole("button", { name: "boardFullscreen" }));
  expect(openImagePreview).toHaveBeenCalledWith({ src: assetFileUrl("vid-1"), title: "素材 vid-1", video: true, gallery: batch });
});

it("图点一下就开,画廊是同一批", async () => {
  renderResult();
  fireEvent.click(await screen.findByRole("button", { name: "素材 img-1" }));
  expect(openImagePreview).toHaveBeenCalledWith({ src: assetPreviewUrl("img-1"), title: "素材 img-1", gallery: batch });
});
