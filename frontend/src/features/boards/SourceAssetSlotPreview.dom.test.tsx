/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openImagePreview = vi.fn();
const modal = vi.fn();

vi.mock("@/components/app/image-preview", () => ({
  useImagePreview: () => ({ openImagePreview, isImagePreviewOpen: false }),
}));

vi.mock("@/features/media/AssetPreviewModalById", () => ({
  AssetPreviewModalById: (props: { id: string | null }) => {
    modal(props);
    return props.id ? <div data-testid="asset-preview-modal">{props.id}</div> : null;
  },
}));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => ({
    boardPreviewSource: "预览{name}",
    boardRemove: "移除",
  })[key] ?? key,
}));

vi.mock("@/api/client", async () => ({
  assetFileUrl: (id: string) => `/files/${id}`,
  assetPreviewUrl: (id: string) => `/previews/${id}`,
  assetThumbnailUrl: (id: string) => `/thumbnails/${id}`,
}));

import { SourceAssetSlotPreview } from "./SourceAssetSlotPreview";

describe("生成节点的参考素材预览", () => {
  beforeEach(() => {
    openImagePreview.mockReset();
    modal.mockClear();
  });

  it("音频不请求缩略图，点击后打开素材详情弹窗", () => {
    const { container } = render(
      <SourceAssetSlotPreview assetId="audio-1" kind="audio" label="参考音频" onRemove={() => {}} />,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("audio")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "预览参考音频" }));
    expect(screen.getByTestId("asset-preview-modal")).toHaveTextContent("audio-1");
    expect(openImagePreview).not.toHaveBeenCalled();
  });

  it("视频仍使用视频灯箱，而不是图片灯箱", () => {
    render(<SourceAssetSlotPreview assetId="video-1" kind="video" label="参考视频" onRemove={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "预览参考视频" }));
    expect(openImagePreview).toHaveBeenCalledWith({
      src: "/files/video-1",
      title: "参考视频",
      video: true,
    });
  });
});
