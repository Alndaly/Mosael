/** @vitest-environment jsdom */
import { afterEach, expect, it, vi } from "vitest";

/**
 * 「保存到本地」落到磁盘上的是**原始文件**,不是预览。
 *
 * 图在界面里显示的是后端转好的预览(HEIC 这类原图浏览器解不了),所以保存绝不能拿界面上的
 * `src` 去下载 —— 那是转码过的 JPEG。这条钉住三件事:
 *
 * - 走 `/assets/{id}/file`(原始字节),不是 `/preview`;
 * - 文件名 `original_filename || name`(跨域时浏览器忽略 `download` 属性,真正生效的是
 *   `/file` 端点响应头里的 Content-Disposition,见后端 assets.py 的 `get_asset_file`;
 *   这里给的属性是同域场景和 Electron 的兜底);
 * - 点完把临时锚点摘掉,不在 DOM 里留一串。
 *
 * 三类媒体(图、视频、音频)在这里是同一条路:素材登记时原文件就在盘上,`/file` 原样发回来。
 */

vi.mock("@/api/client", () => ({ assetFileUrl: (id: string) => `/api/assets/${id}/file` }));

import { saveAssetToDisk } from "@/lib/download";

/** 在 `click()` 的那一刻把锚点抓下来 —— 它随即就被摘掉了。 */
function clickAnchor(asset: { id: string; name: string; original_filename: string }): HTMLAnchorElement {
  const clicked: HTMLAnchorElement[] = [];
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push(this);
  });
  saveAssetToDisk(asset);
  click.mockRestore();
  expect(clicked).toHaveLength(1);
  expect(document.querySelectorAll("a")).toHaveLength(0);
  return clicked[0];
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

it("图片:取原文件端点,文件名优先用 original_filename(存下来的是 HEIC,不是转好的预览)", () => {
  const anchor = clickAnchor({ id: "a1", name: "IMG_0665", original_filename: "IMG_0665.HEIC" });

  expect(anchor.getAttribute("href")).toBe("/api/assets/a1/file");
  expect(anchor.getAttribute("href")).not.toContain("preview");
  expect(anchor.download).toBe("IMG_0665.HEIC");
});

it("视频:同一个端点,original_filename 给了就用它(没有才退回 name)", () => {
  expect(clickAnchor({ id: "v1", name: "片头", original_filename: "opening.mp4" }).download).toBe("opening.mp4");
  expect(clickAnchor({ id: "v1", name: "片头", original_filename: "" }).download).toBe("片头");
});

it("音频:同一个端点、同一套文件名规则", () => {
  const anchor = clickAnchor({ id: "s1", name: "配音", original_filename: "speech.wav" });

  expect(anchor.getAttribute("href")).toBe("/api/assets/s1/file");
  expect(anchor.download).toBe("speech.wav");
});
