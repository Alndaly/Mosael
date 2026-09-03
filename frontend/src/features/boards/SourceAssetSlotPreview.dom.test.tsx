/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openImagePreview = vi.fn();

vi.mock("@/components/app/image-preview", () => ({
  useImagePreview: () => ({ openImagePreview, isImagePreviewOpen: false }),
}));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => ({
    boardPlaySource: "播放{name}",
    boardPauseSource: "暂停{name}",
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
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  });

  it("音频显示音频控件，不请求缩略图也不打开图片灯箱", () => {
    const { container } = render(
      <SourceAssetSlotPreview assetId="audio-1" kind="audio" label="参考音频" onRemove={() => {}} />,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("audio")).toHaveAttribute("src", "/files/audio-1");

    fireEvent.click(screen.getByRole("button", { name: "播放参考音频" }));
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledOnce();
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
