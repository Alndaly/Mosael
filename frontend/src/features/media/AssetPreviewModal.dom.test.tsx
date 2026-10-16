/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";


const openImagePreview = vi.fn();
let imagePreviewOpen = false;

vi.mock("@/api/client", () => ({
  assetFileUrl: (id: string) => `/file/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  fetchWaveform: async () => ({ peaks: [] }),
  //: 视频详情右栏的「镜头」那一块自己取数(ADR 0061 §5);它有自己的测试(ShotBreakdownPanel.dom.test.tsx)。
  getShotBreakdown: async () => ({ asset_id: "clip-asset", status: "none", shots: [], hints: [], describe: {} }),
  //: 节奏条要的那条动静曲线(同一块自己有测试);没拆过时它根本不问(见 ShotBreakdownPanel 的 enabled)。
  getShotMotionTrack: async () => ({ asset_id: "clip-asset", status: "none", hz: 0, points: 0, values: [] }),
  startShotBreakdown: async () => ({}),
  listJobs: async () => [],
  //: 「清除元数据」(ADR 0062)那一块自己取数;它有自己的测试(ScrubMetadata.dom.test.tsx)。
  //: 这里只要求它别干扰"详情页有哪几块"这件事:没有清除任务,就没有那一块。
  SCRUB_JOB_KIND: "scrub_metadata",
  getScrubReport: async () => ({ asset_id: "clip-asset", status: "none", markdown: "" }),
  scrubOutcomeOf: () => null,
  startScrub: async () => ({}),
}));

//: 「存成笔记」走它自己的中文案表和笔记查询,和这里要测的预览层次无关。
vi.mock("@/features/notes/SaveToNote", () => ({ SaveToNote: () => null }));

//: 「属于哪些资产」那一行自己取数(资产库,ADR 0027),和这里要测的预览层次无关。
vi.mock("@/features/entities/AssetEntities", () => ({ AssetEntitiesList: () => null }));
//: 文档的阅读器自己取数(解析结果),有它自己的测试。
vi.mock("@/features/media/DocumentReader", () => ({ DocumentReader: () => <div data-document-reader="" /> }));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
}));

vi.mock("@/components/app/image-preview", () => ({
  useImagePreview: () => ({ openImagePreview, isImagePreviewOpen: imagePreviewOpen }),
}));

vi.mock("@/lib/download", () => ({ saveAssetToDisk: vi.fn() }));

import { AssetPreviewModal } from "./AssetPreviewModal";
import { saveAssetToDisk } from "@/lib/download";

const imageAsset = {
  id: "heic-asset",
  name: "IMG_0665.HEIC",
  original_filename: "IMG_0665.HEIC",
  kind: "image",
  source: "imported",
  tags: [],
  created_at: "2026-08-30T12:14:00",
  media_info: { width: 512, height: 512 },
};

const audioAsset = {
  ...imageAsset,
  id: "audio-asset",
  name: "longxiaochun_v2 · 配音",
  original_filename: "speech.wav",
  kind: "audio",
  media_info: { duration: 2.9 },
};

const videoAsset = {
  ...imageAsset,
  id: "clip-asset",
  name: "片头.mp4",
  original_filename: "opening.mp4",
  kind: "video",
  media_info: { width: 1920, height: 1080, duration: 3.5, fps: 24 },
};

/** 右栏的「镜头」那一块(ADR 0061 §5)自己取数,要一个查询上下文。 */
function show(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("AssetPreviewModal", () => {
  beforeEach(() => {
    openImagePreview.mockReset();
    vi.mocked(saveAssetToDisk).mockReset();
    imagePreviewOpen = false;
  });

  it("uses the browser-compatible image endpoint in both inline and zoomed previews", () => {
    show(<AssetPreviewModal asset={imageAsset as never} onClose={vi.fn()} />);

    const image = screen.getByRole("img", { name: "IMG_0665.HEIC" });
    expect(image.getAttribute("src")).toBe("/preview/heic-asset");

    fireEvent.click(screen.getByRole("button", { name: /assetClickToZoom/ }));
    expect(openImagePreview).toHaveBeenCalledWith({
      src: "/preview/heic-asset",
      title: "IMG_0665.HEIC",
      //: 灯箱里那颗「保存到本地」要知道存的是哪一份(详见 image-preview.tsx)。
      assetId: "heic-asset",
    });
  });

  //: 维护者:所有图片/视频/音频预览的窗口都要有「保存到本地」—— 此前只有素材管理页那一颗。
  //: 详情弹窗是这条链上的总入口(工具结果、附件、画板参考槽、笔记引用都开它),
  //: 所以三类的默认动作都摆在它自己的头部,不靠每个调用方记得传。
  it("图片:头部默认就有一颗「保存到本地」,点了保存的是这一份", () => {
    show(<AssetPreviewModal asset={imageAsset as never} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "assetSaveLocal" }));

    expect(saveAssetToDisk).toHaveBeenCalledWith(imageAsset);
  });

  it("视频:头部默认就有一颗「保存到本地」,点了保存的是这一份(取原文件字节,不是预览图)", () => {
    show(<AssetPreviewModal asset={videoAsset as never} onClose={vi.fn()} />);

    expect(document.querySelector("[data-media-preview-player]")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "assetSaveLocal" }));

    expect(saveAssetToDisk).toHaveBeenCalledWith(videoAsset);
  });

  it("音频:头部默认就有一颗「保存到本地」,点了保存的是这一份", () => {
    show(<AssetPreviewModal asset={audioAsset as never} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "assetSaveLocal" }));

    expect(saveAssetToDisk).toHaveBeenCalledWith(audioAsset);
  });

  it("文档(ADR 0031)不当图片画,放解析出的阅读器;没有「属于哪些资产」", () => {
    const doc = { ...imageAsset, id: "doc", name: "方案.pptx", original_filename: "方案.pptx", kind: "document",
                  media_info: { format: "pptx", size_bytes: 2048 } };
    show(<AssetPreviewModal asset={doc as never} onClose={vi.fn()} />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(document.querySelector("[data-document-reader]")).not.toBeNull();
    expect(screen.queryByText("assetEntitiesTitle")).toBeNull();
    expect(screen.getByText("kindDocument")).toBeTruthy();
  });

  it("renders audio with the shared custom player instead of native controls", () => {
    show(<AssetPreviewModal asset={audioAsset as never} onClose={vi.fn()} />);

    // Dialog content is portaled into document.body, outside Testing Library's render container.
    const audio = document.querySelector("audio");
    expect(audio).not.toBeNull();
    expect(audio?.getAttribute("src")).toBe("/file/audio-asset");
    expect(audio?.hasAttribute("controls")).toBe(false);
    expect(audio?.hasAttribute("autoplay")).toBe(true);
    expect(screen.getByRole("button", { name: "boardPlay" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "boardMute" })).toBeInTheDocument();
  });

  it("keeps the asset details open while the fullscreen image preview is open", () => {
    imagePreviewOpen = true;
    const onClose = vi.fn();
    show(<AssetPreviewModal asset={imageAsset as never} onClose={onClose} />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).not.toHaveBeenCalled();
  });

  it("still closes the asset details when no fullscreen preview is open", () => {
    const onClose = vi.fn();
    show(<AssetPreviewModal asset={imageAsset as never} onClose={onClose} />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledOnce();
  });

  //: 体检 UM-13:详情里此前一个操作都没有,从 ⌘K、深链、通知跳过来看完想改名、删掉,只能关掉再回网格里找。
  //: 调用方自己那一组里已经有「保存到本地」时不摆第二颗 —— 同一条动作两遍会挤掉「改名」「打标签」。
  it("给了动作就在头部摆出来:前三个是按钮,其余(含删除)收进 ⋯;自带的那颗不重复摆", () => {
    const rename = vi.fn();
    const remove = vi.fn();
    const actions = vi.fn(() => [
      { label: "assetSaveLocal", icon: null, onSelect: vi.fn() },
      { label: "rename", icon: null, onSelect: rename },
      { label: "editTags", icon: null, onSelect: vi.fn() },
      { label: "assetSetAsReference", icon: null, onSelect: vi.fn() },
      { label: "delete", icon: null, destructive: true, onSelect: remove },
    ]);
    const view = show(<AssetPreviewModal asset={imageAsset as never} onClose={vi.fn()} actions={actions} />);
    expect(actions).toHaveBeenCalledWith(imageAsset);
    const bar = document.querySelector("[data-asset-detail-actions]") as HTMLElement;
    expect([...bar.querySelectorAll(":scope > button")].map((one) => one.textContent)).toEqual(["assetSaveLocal", "rename", "editTags", ""]);
    fireEvent.click(screen.getByRole("button", { name: "rename" }));
    expect(rename).toHaveBeenCalled();
    view.unmount();

    //: 没给动作的地方(只读的工具结果、附件预览)也照样有「保存到本地」—— 这条是这次改动的重点。
    show(<AssetPreviewModal asset={imageAsset as never} onClose={vi.fn()} />);
    const builtin = document.querySelector("[data-asset-detail-actions]") as HTMLElement;
    expect([...builtin.querySelectorAll(":scope > button")].map((one) => one.textContent)).toEqual(["assetSaveLocal"]);
  });
});
