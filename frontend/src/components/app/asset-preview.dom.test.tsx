/** @vitest-environment jsdom */
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openImagePreview = vi.fn();
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/components/app/image-preview", () => ({
  useImagePreview: () => ({ openImagePreview }),
}));
//: 两个地址都取不到时去问这份素材还在不在:`gone` 是服务端回 404,别的 id 都还在(一时取不到)。
const getAsset = vi.fn((id: string) => (id.startsWith("gone") ? Promise.reject(new Error("404")) : Promise.resolve({ id })));
vi.mock("@/api/client", () => ({
  assetFileUrl: (id: string) => `/file/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  getAsset: (id: string) => getAsset(id),
  isNotFound: (error: unknown) => error instanceof Error && error.message === "404",
}));

import { AssetInlinePreview } from "./asset-preview";

beforeEach(() => {
  openImagePreview.mockReset();
  getAsset.mockClear();
});

/** 占位出来(问素材在不在是异步的)。 */
function placeholderIn(container: HTMLElement) {
  return waitFor(() => {
    const found = container.querySelector<HTMLElement>("[data-asset-missing]");
    if (!found) throw new Error("占位还没出来");
    return found;
  });
}

/** 预览地址和原文件先后都取不到。 */
function failBoth(container: HTMLElement) {
  fireEvent.error(container.querySelector("img")!);
  fireEvent.error(container.querySelector("img")!);
}

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
      //: 灯箱顶上那颗「保存到本地」按它取原始文件。
      assetId: "a",
      gallery,
    });
  });
});

it("falls back to original image bytes and shows a helpful state if both endpoints fail", async () => {
  const { container, rerender } = render(<AssetInlinePreview assetId="gone-scene" name="Scene" kind="image" preview="off" imageFallback={<span>Preview unavailable</span>} />);
  fireEvent.error(container.querySelector("img")!);
  expect(container.querySelector("img")?.getAttribute("src")).toBe("/file/gone-scene");
  fireEvent.error(container.querySelector("img")!);
  await waitFor(() => expect(container.querySelector("img")).toBeNull());
  expect(container.textContent).toBe("Preview unavailable");
  rerender(<AssetInlinePreview assetId="new-frame" name="Scene" kind="image" preview="off" imageFallback={<span>Preview unavailable</span>} />);
  expect(container.querySelector("img")?.getAttribute("src")).toBe("/preview/new-frame");
});

//: 素材被删掉之后:两个地址都 404。此前这里留着一张浏览器的破图(界面上就是个「坏了的图片」)。
//: 维护者截图:无限画布、工作流节点里的产出被删之后,占位是一大块空盒子 —— 图标在上、字在下,中间一片空。
//: 原因:调用方给的是照 `<img>` 写的类(`object-cover`),而 `place-items-center` 在高的盒子里会把两个网格行拉开。
it("占位不照抄图片的类,内容整块居中(尺寸照旧,不跳版)", async () => {
  const { container } = render(
    <AssetInlinePreview assetId="gone" name="被删的那张" kind="image" preview="off" plain
                        className="h-[72px] w-full overflow-hidden object-cover rounded-xl" />);
  failBoth(container);
  const placeholder = await placeholderIn(container);
  const classes = placeholder.className.split(/\s+/);
  expect(classes, "整块居中,不是把两行撑开").toContain("place-content-center");
  expect(classes.some((one) => one.startsWith("object-")), "图片专有的类对块没有意义").toBe(false);
  expect(classes, "尺寸和圆角照旧 —— 占的还是原来那张图的位置").toEqual(
    expect.arrayContaining(["h-[72px]", "w-full", "rounded-xl"]));
  expect(placeholder.textContent).toBe("assetPreviewGone");
});

it("两个地址都不通、服务端说素材不在了:给一块「素材已删除」的占位,不是破图,也没有重试", async () => {
  const { container } = render(<AssetInlinePreview assetId="gone" name="被删的那张" kind="image" preview="off" />);
  failBoth(container);
  const placeholder = await placeholderIn(container);
  expect(container.querySelector("img"), "不再留着一张取不到的图").toBeNull();
  expect(placeholder.getAttribute("aria-label")).toBe("被删的那张: assetPreviewGone");
  expect(screen.queryByRole("button", { name: "assetPreviewRetry" })).toBeNull();
});

it("两个地址都不通、素材其实还在(后端重启、网络抖):不说「已删除」,说加载不出来,能点重试", async () => {
  const { container } = render(<AssetInlinePreview assetId="alive" name="还在的那张" kind="image" preview="off" />);
  failBoth(container);
  const placeholder = await placeholderIn(container);
  expect(placeholder.getAttribute("aria-label")).toBe("还在的那张: assetPreviewUnavailable");
  fireEvent.click(screen.getByRole("button", { name: "assetPreviewRetry" }));
  //: 重试从预览地址重新取,地址带上第几轮 —— 同一个地址的失败浏览器会直接用缓存的结果。
  expect(container.querySelector("img")?.getAttribute("src")).toBe("/preview/alive?retry=1");
});

it("一时取不到的图隔一会儿自己再取:后端重启完,不用切页面就回来", async () => {
  vi.useFakeTimers();
  try {
    const { container } = render(<AssetInlinePreview assetId="alive" name="还在的那张" kind="image" preview="off" />);
    failBoth(container);
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector("[data-asset-missing]")).not.toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(container.querySelector("img")?.getAttribute("src")).toBe("/preview/alive?retry=1");
  } finally {
    vi.useRealTimers();
  }
});
