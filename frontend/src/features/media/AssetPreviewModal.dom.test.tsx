/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openImagePreview = vi.fn();
let imagePreviewOpen = false;

vi.mock("@/api/client", () => ({
  assetFileUrl: (id: string) => `/file/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  fetchWaveform: async () => ({ peaks: [] }),
}));

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

import { AssetPreviewModal } from "./AssetPreviewModal";

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

describe("AssetPreviewModal", () => {
  beforeEach(() => {
    openImagePreview.mockReset();
    imagePreviewOpen = false;
  });

  it("uses the browser-compatible image endpoint in both inline and zoomed previews", () => {
    render(<AssetPreviewModal asset={imageAsset as never} onClose={vi.fn()} />);

    const image = screen.getByRole("img", { name: "IMG_0665.HEIC" });
    expect(image.getAttribute("src")).toBe("/preview/heic-asset");

    fireEvent.click(screen.getByTitle("assetClickToZoom"));
    expect(openImagePreview).toHaveBeenCalledWith({
      src: "/preview/heic-asset",
      title: "IMG_0665.HEIC",
    });
  });

  it("文档(ADR 0031)不当图片画,放解析出的阅读器;没有「属于哪些资产」", () => {
    const doc = { ...imageAsset, id: "doc", name: "方案.pptx", original_filename: "方案.pptx", kind: "document",
                  media_info: { format: "pptx", size_bytes: 2048 } };
    render(<AssetPreviewModal asset={doc as never} onClose={vi.fn()} />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(document.querySelector("[data-document-reader]")).not.toBeNull();
    expect(screen.queryByText("assetEntitiesTitle")).toBeNull();
    expect(screen.getByText("kindDocument")).toBeTruthy();
  });

  it("renders audio with the shared custom player instead of native controls", () => {
    render(<AssetPreviewModal asset={audioAsset as never} onClose={vi.fn()} />);

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
    render(<AssetPreviewModal asset={imageAsset as never} onClose={onClose} />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).not.toHaveBeenCalled();
  });

  it("still closes the asset details when no fullscreen preview is open", () => {
    const onClose = vi.fn();
    render(<AssetPreviewModal asset={imageAsset as never} onClose={onClose} />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledOnce();
  });
});
