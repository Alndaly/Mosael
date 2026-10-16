/** @vitest-environment jsdom */
/**
 * 「点一行播放器跳到那一镜」(ADR 0061 §5)—— 接的是**详情页现有的那个播放器**,不另造一个。
 *
 * 面板自己不碰 `<video>`:它只把这一镜的 `start` 报上去,由详情把这次「要跳到第几秒」交给
 * `MediaPreviewPlayer`。所以这里把播放器换成一个只记下这件事的替身 —— 断言的是**跳转请求真的
 * 递到了播放器手里、而且是那一镜的秒数**;播放器自己怎么跳由
 * `components/app/MediaPreviewPlayer.dom.test.tsx` 盯着。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import type { ShotBreakdown } from "@/api/domains/shots";

const seeked = vi.hoisted(() => ({ current: [] as number[] }));

vi.mock("@/components/app/MediaPreviewPlayer", () => ({
  MediaPreviewPlayer: ({ seekTo }: { seekTo?: { seconds: number } | null }) => {
    if (seekTo) seeked.current.push(seekTo.seconds);
    return <div data-media-preview-player="" data-seek={seekTo ? String(seekTo.seconds) : ""} />;
  },
}));

vi.mock("@/app/preferences", async () => {
  const { zhCN } = await import("@/app/messages/zh-CN");
  const table = zhCN as unknown as Record<string, string>;
  return { useI18n: () => (key: string) => table[key] ?? key };
});

vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn(), isImagePreviewOpen: false }) }));
vi.mock("@/features/entities/AssetEntities", () => ({ AssetEntitiesList: () => null }));
vi.mock("@/features/media/DocumentReader", () => ({ DocumentReader: () => null }));
vi.mock("@/lib/download", () => ({ saveAssetToDisk: vi.fn() }));
vi.mock("@/features/notes/SaveToNote", () => ({ SaveToNote: () => null }));

const breakdown: ShotBreakdown = {
  asset_id: "clip",
  status: "ready",
  id: "b1",
  lang: "zh",
  shots: [
    { id: "S01", start: 0, end: 2.6, seconds: 2.6, motion: 3.2, dialogue: "", size: "medium", camera: ["static"], frame: "开场" },
    { id: "S02", start: 12.4, end: 15, seconds: 2.6, motion: 0.4, dialogue: "你要点什么?", size: "close", camera: ["static"], frame: "菜单" },
  ],
  hints: [],
  describe: { provider: "kimi", model: "m1", batches: 1, judged_batches: 1, error: "" },
  report_markdown: "# 镜头表",
  storyboard_markdown: "## 分镜",
} as unknown as ShotBreakdown;

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  getShotBreakdown: async () => breakdown,
  startShotBreakdown: vi.fn(),
  listJobs: async () => [],
}));

import { AssetPreviewModal } from "./AssetPreviewModal";

const videoAsset = {
  id: "clip",
  workspace_id: "ws",
  name: "片头.mp4",
  original_filename: "opening.mp4",
  kind: "video",
  source: "imported",
  tags: [],
  media_info: { width: 1920, height: 1080, duration: 40, fps: 24 },
} as never;

afterEach(() => {
  cleanup();
  seeked.current = [];
});

it("点某一镜那一行,播放器跳到它的 start", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  //: Dialog 渲染在 document.body 里(portal),不在 render 的那个容器里。
  render(
    <QueryClientProvider client={client}>
      <AssetPreviewModal asset={videoAsset} onClose={vi.fn()} />
    </QueryClientProvider>,
  );

  //: 播放器还是详情页那一个(左栏),没有因为多了镜头表就换掉。
  expect(document.querySelector("[data-media-preview-player]")).not.toBeNull();
  await waitFor(() => expect(document.querySelectorAll("[data-shot-row]")).toHaveLength(2));

  const second = document.querySelectorAll<HTMLElement>("[data-shot-row]")[1];
  fireEvent.click(second);

  expect(seeked.current).toEqual([12.4]);
  expect(document.querySelector("[data-media-preview-player]")?.getAttribute("data-seek")).toBe("12.4");
});

it("图片没有镜头那一块", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  render(
    <QueryClientProvider client={client}>
      <AssetPreviewModal asset={{ ...(videoAsset as object), kind: "image" } as never} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
  expect(document.querySelector("[data-shot-breakdown]")).toBeNull();
  expect(screen.queryByRole("button", { name: /拆镜头/ })).toBeNull();
});
