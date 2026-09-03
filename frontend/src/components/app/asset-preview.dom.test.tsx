/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openImagePreview = vi.fn();
vi.mock("@/components/app/image-preview", () => ({
  useImagePreview: () => ({ openImagePreview }),
}));
vi.mock("@/api/client", () => ({
  assetFileUrl: (id: string) => `/file/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
}));

import { AssetInlinePreview } from "./asset-preview";

beforeEach(() => openImagePreview.mockReset());

describe("素材行内预览", () => {
  it("plain 视频预览的容器铺满调用方宽度", () => {
    const { container } = render(
      <AssetInlinePreview assetId="v" name="视频" kind="video" plain className="h-20 w-full object-cover" />,
    );

    const video = container.querySelector("video");
    expect(video).not.toBeNull();
    expect(video?.parentElement?.className).toContain("w-full");
    expect(video?.parentElement?.className).not.toContain("w-fit");
  });

  it("图片显示兼容预览,点开时把整段聊天媒体交给 react-photo-view", () => {
    const gallery = [
      { src: "/preview/a", title: "第一张" },
      { src: "/preview/b", title: "第二张" },
      { src: "/file/v", title: "视频", video: true },
    ];
    render(<AssetInlinePreview assetId="a" name="第一张" kind="image" gallery={gallery} />);

    expect(screen.getByRole("img", { name: "第一张" }).getAttribute("src")).toBe("/preview/a");
    fireEvent.click(screen.getByRole("button", { name: "第一张" }));
    expect(openImagePreview).toHaveBeenCalledWith({
      src: "/preview/a",
      title: "第一张",
      gallery,
    });
  });
});
