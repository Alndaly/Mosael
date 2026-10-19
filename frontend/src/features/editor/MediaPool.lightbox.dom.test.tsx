/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

/**
 * 剪辑页素材面板 ->「看大图」这条真实的接线(维护者报的就是这里):
 * 点第一个视频,只有它一个挂播放器;翻到第二个,第一个被卸掉;关掉之后一个都不剩。
 *
 * 这个用例**不 mock 灯箱** —— 接线本身(MediaPool 把整份清单当画廊交给 openImagePreview)也是被测的一部分。
 */
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => (key === "viewFullSizeOf" ? "看大图:{name}" : key),
}));

//: 灯箱库按 `"ontouchstart" in window` 选手势那一套;jsdom 有这个属性,桌面版没有 —— 拿掉它,走鼠标那一套(才会画左右箭头)。
vi.hoisted(() => {
  for (let proto = Object.getPrototypeOf(window); proto; proto = Object.getPrototypeOf(proto)) {
    if (Object.prototype.hasOwnProperty.call(proto, "ontouchstart")) delete (proto as Record<string, unknown>).ontouchstart;
  }
  delete (window as unknown as Record<string, unknown>).ontouchstart;
});

import { assetFileUrl, type AssetCard } from "@/api/client";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { MediaPool } from "./MediaPool";

const asset = (id: string, kind: string): AssetCard => ({
  id, name: id, workspace_id: "ws", project_id: "p", original_filename: id, kind, source: "imported", tags: [],
  derived: false, ai_generated: false, intermediate: "",
  media_info: { duration: 10, width: 1920, height: 1080, fps: 25, has_thumbnail: false, format: null, pages: null, size_bytes: null },
});
//: 两个视频挨着 —— 灯箱画廊里它们就是相邻的两项。
const ASSETS = [asset("beach", "video"), asset("pier", "video")];

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  listAssetPage: vi.fn(async () => ({ items: ASSETS, next_cursor: null, total: ASSETS.length })),
  getAssetFacets: vi.fn(async () => ({ total: ASSETS.length, kinds: { video: 2 }, tags: {}, intermediates: {} })),
}));

const portal = () => document.querySelector<HTMLElement>(".PhotoView-Portal");
const sources = () => [...document.querySelectorAll<HTMLMediaElement>(".PhotoView-Portal video[src], .PhotoView-Portal audio[src]")];
const srcs = () => sources().map((element) => element.getAttribute("src"));

afterEach(() => {
  cleanup();
  localStorage.clear();
});

async function renderPool() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
        <MediaPool workspaceId="ws" projectId="p" uploading={false} onImportFiles={vi.fn()} onRecord={vi.fn()} onAddToTimeline={vi.fn()} />
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
  await waitFor(() => expect(document.querySelector("[data-pool-item]")).not.toBeNull());
}

it("点素材清单里第一个视频:只有它一个带源;翻到第二个:第一个卸掉;关掉:一个不剩", async () => {
  await renderPool();
  fireEvent.click(await screen.findByRole("button", { name: "看大图:beach" }));

  await waitFor(() => expect(portal()).not.toBeNull());
  await waitFor(() => expect(sources()).toHaveLength(1));
  expect(srcs()).toEqual([assetFileUrl("beach")]);

  fireEvent.click(document.querySelector<HTMLElement>(".PhotoView-Slider__ArrowRight")!);
  await waitFor(() => expect(srcs()).toEqual([assetFileUrl("pier")]));
  expect(document.querySelector(`.PhotoView-Portal video[src="${assetFileUrl("beach")}"]`)).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "imagePreviewClose" }));
  await waitFor(() => expect(document.querySelectorAll(".PhotoView-Portal video, .PhotoView-Portal audio")).toHaveLength(0));
});
