/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 一次运行的产出怎么开大图。
 *
 * 画布上点节点是「选中它」(检查器跟着出来),所以那里的图不接管点击,角上压一颗「看大图」;检查器、执行历史里
 * 点图就开。两处打开的都是**这一组**:这一步的几份,或者执行历史给的整次运行。
 */

const openImagePreview = vi.hoisted(() => vi.fn());
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview, isImagePreviewOpen: false }) }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => (key === "viewFullSizeOf" ? "看大图:{name}" : key),
}));
vi.mock("@/api/transport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/transport")>()),
  api: vi.fn(async (path: string) => {
    const id = path.split("/").pop() as string;
    return { id, name: `素材 ${id}`, original_filename: `${id}.bin`, kind: id.startsWith("vid") ? "video" : "image" };
  }),
}));

import { assetFileUrl, assetPreviewUrl } from "@/api/client";
import { OutputAssets } from "@/features/workflows/OutputAssets";

const FIRST = { key: "image", label: "原图", assetId: "img1" };
const SECOND = { key: "upscaled", label: "放大", assetId: "img2" };
const CLIP = { key: "video", label: "成片", assetId: "vid1" };

function mount(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  openImagePreview.mockReset();
});

const stepGallery = [
  { src: assetPreviewUrl("img1"), title: "素材 img1" },
  { src: assetPreviewUrl("img2"), title: "素材 img2" },
];

describe("画布节点上的产出", () => {
  it("点图不开大图(那一下是选中节点);角上那颗「看大图」开这一步的两份,从点的那张开始", async () => {
    mount(<OutputAssets items={[FIRST, SECOND]} density="node" />);
    const zoom = await screen.findByRole("button", { name: "看大图:素材 img2" });
    expect(screen.queryByRole("button", { name: "素材 img2" }), "图本身不是按钮").toBeNull();
    fireEvent.click(screen.getByRole("img", { name: "素材 img2" }));
    expect(openImagePreview).not.toHaveBeenCalled();

    fireEvent.click(zoom);
    expect(openImagePreview).toHaveBeenCalledWith({ src: assetPreviewUrl("img2"), title: "素材 img2", gallery: stepGallery });
  });

  it("「看大图」按下去不冒泡 —— 节点的点击(选中)不跟着发生", async () => {
    const select = vi.fn();
    mount(
      <div onClick={select}>
        <OutputAssets items={[FIRST]} density="node" />
      </div>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "看大图:素材 img1" }));
    expect(openImagePreview).toHaveBeenCalledTimes(1);
    expect(select).not.toHaveBeenCalled();
  });
});

describe("检查器、执行历史里的产出", () => {
  it("点图就开,画廊是这一步的几份", async () => {
    mount(<OutputAssets items={[FIRST, SECOND]} density="panel" />);
    fireEvent.click(await screen.findByRole("button", { name: "素材 img1" }));
    expect(openImagePreview).toHaveBeenCalledWith({ src: assetPreviewUrl("img1"), title: "素材 img1", gallery: stepGallery });
  });

  it("执行历史给了整次运行的画廊:翻的是那一组,不是这一步自己的", async () => {
    const run = [...stepGallery, { src: assetFileUrl("vid1"), title: "素材 vid1", video: true }];
    mount(<OutputAssets items={[SECOND]} density="panel" gallery={run} />);
    fireEvent.click(await screen.findByRole("button", { name: "素材 img2" }));
    expect(openImagePreview).toHaveBeenCalledWith({ src: assetPreviewUrl("img2"), title: "素材 img2", gallery: run });
  });

  it("视频由播放器的「全屏」开同一个灯箱,标着 video", async () => {
    mount(<OutputAssets items={[CLIP]} density="panel" />);
    fireEvent.click(await screen.findByRole("button", { name: "boardFullscreen" }));
    expect(openImagePreview).toHaveBeenCalledWith({
      src: assetFileUrl("vid1"),
      title: "素材 vid1",
      video: true,
      gallery: [{ src: assetFileUrl("vid1"), title: "素材 vid1", video: true }],
    });
  });
});
