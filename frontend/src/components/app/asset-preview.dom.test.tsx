/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openImagePreview = vi.fn();
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
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

it("falls back to original image bytes and shows a helpful state if both endpoints fail", () => {
  const { container, rerender } = render(<AssetInlinePreview assetId="scene" name="Scene" kind="image" preview="off" imageFallback={<span>Preview unavailable</span>} />);
  fireEvent.error(container.querySelector("img")!);
  expect(container.querySelector("img")?.getAttribute("src")).toBe("/file/scene");
  fireEvent.error(container.querySelector("img")!);
  expect(container.querySelector("img")).toBeNull();
  expect(container.textContent).toBe("Preview unavailable");
  rerender(<AssetInlinePreview assetId="new-frame" name="Scene" kind="image" preview="off" imageFallback={<span>Preview unavailable</span>} />);
  expect(container.querySelector("img")?.getAttribute("src")).toBe("/preview/new-frame");
});

//: 素材被删掉之后:两个地址都 404。此前这里留着一张浏览器的破图(界面上就是个「坏了的图片」)。
it("两个地址都不通:默认给一块「素材已删除」的占位,不是破图", () => {
  const { container } = render(<AssetInlinePreview assetId="gone" name="被删的那张" kind="image" preview="off" />);
  fireEvent.error(container.querySelector("img")!);
  fireEvent.error(container.querySelector("img")!);
  expect(container.querySelector("img"), "不再留着一张取不到的图").toBeNull();
  const placeholder = container.querySelector("[data-asset-missing]")!;
  expect(placeholder.getAttribute("aria-label")).toBe("被删的那张: assetPreviewGone");
});
