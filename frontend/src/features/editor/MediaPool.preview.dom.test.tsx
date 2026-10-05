/** @vitest-environment jsdom */
/**
 * 剪辑页素材面板里看大图:缩略图是一颗按钮(键盘走得到、读屏念「看大图:名字」),图和视频都开;
 * 左右翻的是眼下这份清单里的图和视频。这一行拖进时间线、双击加进时间线照旧。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { assetFileUrl, assetPreviewUrl, type AssetCard } from "@/api/client";
import { MediaPool } from "./MediaPool";

const openImagePreview = vi.hoisted(() => vi.fn());
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview, isImagePreviewOpen: false }) }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => (key === "viewFullSizeOf" ? "看大图:{name}" : key),
}));

const asset = (id: string, kind: string): AssetCard => ({
  id, name: id, workspace_id: "ws", project_id: "p", original_filename: id, kind, source: "imported", tags: [],
  derived: false, ai_generated: false, intermediate: "",
  media_info: { duration: null, width: null, height: null, fps: null, has_thumbnail: false, format: null, pages: null, size_bytes: null },
});
const ASSETS = [asset("beach", "video"), asset("plain", "audio"), asset("pier", "image")];

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  listAssetPage: vi.fn(async () => ({ items: ASSETS, next_cursor: null, total: ASSETS.length })),
  getAssetFacets: vi.fn(async () => ({ total: ASSETS.length, kinds: { video: 1, image: 1, audio: 1 }, tags: {}, intermediates: {} })),
}));

afterEach(() => {
  cleanup();
  openImagePreview.mockReset();
  localStorage.clear();
});

async function renderPool(onAddToTimeline = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MediaPool workspaceId="ws" projectId="p" uploading={false} onImportFiles={vi.fn()} onRecord={vi.fn()} onAddToTimeline={onAddToTimeline} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(document.querySelector("[data-pool-item]")).not.toBeNull());
  return onAddToTimeline;
}

const pool = [
  { src: assetFileUrl("beach"), title: "beach", video: true },
  { src: assetPreviewUrl("pier"), title: "pier" },
];

it("图和视频的缩略图是「看大图」按钮;音频的不是", async () => {
  await renderPool();
  expect(screen.getByRole("button", { name: "看大图:pier" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "看大图:beach" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "看大图:plain" })).toBeNull();
});

it("点开视频:同一个灯箱换成播放器,左右翻的是清单里的图和视频", async () => {
  await renderPool();
  fireEvent.click(screen.getByRole("button", { name: "看大图:beach" }));
  expect(openImagePreview).toHaveBeenCalledWith({ src: assetFileUrl("beach"), title: "beach", video: true, gallery: pool });
});

it("键盘也开得了:走到缩略图上按回车", async () => {
  await renderPool();
  const thumb = screen.getByRole("button", { name: "看大图:pier" });
  thumb.focus();
  expect(document.activeElement).toBe(thumb);
  await userEvent.setup().keyboard("{Enter}");
  expect(openImagePreview).toHaveBeenCalledWith({ src: assetPreviewUrl("pier"), title: "pier", gallery: pool });
});

it("双击这一行仍然是加进时间线", async () => {
  const onAdd = await renderPool();
  fireEvent.doubleClick(document.querySelector('[data-pool-item="pier"] strong')!);
  expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ id: "pier" }));
  expect(openImagePreview).not.toHaveBeenCalled();
});
