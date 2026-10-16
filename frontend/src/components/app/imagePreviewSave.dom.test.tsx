/** @vitest-environment jsdom */
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

/**
 * 灯箱(全站图片/视频的「点开大图」)顶上那一颗「保存到本地」。
 *
 * 此前想存一张图只能跑去素材管理页:灯箱自己只有「打开原图」—— 那是把文件在新标签页里打开,
 * 图片走的还是后端转好的**预览**地址(HEIC 这类原图浏览器解不了),下载下来不是原始文件。
 * 所以保存要按素材 id 走 `/assets/{id}/file`(原始字节 + 原始文件名)。
 *
 * 灯箱里也挂着**不是素材**的东西:笔记/Markdown 正文里的图、内嵌浏览器的截图、任务失败的
 * 整页截图 —— 那些没有素材可存,这一颗就不摆(原样保留「打开原图」)。
 */

const saveAssetToDisk = vi.hoisted(() => vi.fn());
vi.mock("@/lib/download", () => ({ saveAssetToDisk }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { ImagePreviewProvider, useImagePreview } from "@/components/app/image-preview";
import type { ImagePreviewItem } from "@/components/app/imagePreviewContext";

const items: ImagePreviewItem[] = [
  { src: "/preview/img-1", title: "一张图.png", assetId: "img-1" },
  { src: "/file/vid-1", title: "一段片.mp4", video: true, assetId: "vid-1" },
  //: 不是素材的:笔记正文里的图(没有 id 可存)。
  { src: "https://example.com/plain.png", title: "正文里的图" },
];

function Opener({ at }: { at: number }) {
  const { openImagePreview } = useImagePreview();
  return (
    <button type="button" onClick={() => openImagePreview({ ...items[at], gallery: items })}>
      看大图
    </button>
  );
}

const portal = () => document.querySelector<HTMLElement>(".PhotoView-Portal");

async function open(at: number) {
  render(
    <ImagePreviewProvider>
      <Opener at={at} />
    </ImagePreviewProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "看大图" }));
  await waitFor(() => expect(portal()).not.toBeNull());
}

afterEach(() => {
  cleanup();
  saveAssetToDisk.mockReset();
});

it("图:灯箱顶上有一颗「保存到本地」,点了存的是这份素材(按 id 取原文件)", async () => {
  await open(0);

  fireEvent.click(screen.getByRole("button", { name: "assetSaveLocal" }));

  //: 文件名由 `/file` 端点的 Content-Disposition 给(跨域时 download 属性会被忽略),
  //: 这里能给的只有名字兜底 —— 和 AI 工作台音频结果那颗同一写法。
  expect(saveAssetToDisk).toHaveBeenCalledWith({ id: "img-1", name: "一张图.png", original_filename: "" });
});

it("视频:同一个灯箱里换成播放器,顶上那颗照样在,点了存的是这段片子", async () => {
  await open(1);

  expect(document.querySelector("[data-video-backdrop]")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "assetSaveLocal" }));

  expect(saveAssetToDisk).toHaveBeenCalledWith({ id: "vid-1", name: "一段片.mp4", original_filename: "" });
});

it("不是素材的图(笔记正文、浏览器截图):没有素材可存,就不摆这一颗,「打开原图」照旧", async () => {
  await open(2);

  expect(screen.queryByRole("button", { name: "assetSaveLocal" })).toBeNull();
  expect(portal()?.querySelector('a[href="https://example.com/plain.png"]')).not.toBeNull();
});
