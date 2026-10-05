import { describe, expect, it } from "vitest";

import { assetFileUrl, assetPreviewUrl, type BoardItem } from "@/api/client";
import { boardPreviewGallery } from "./boardPreview";

/**
 * 画板上框选几格之后「预览」:灯箱里左右翻的是选中的图和视频,按画板上读的顺序。
 */

const cell = (id: string, kind: BoardItem["kind"], x: number, y: number, extra: Partial<BoardItem> = {}): BoardItem => ({
  id, kind, x, y, width: 200, height: 160, asset_id: `a-${id}`, title: id, ...extra,
});

describe("画板选中的那几格怎么排进灯箱", () => {
  it("只收已经有素材的图片格、视频格;视频那一项标着 video", () => {
    const gallery = boardPreviewGallery([
      cell("photo", "image", 0, 0),
      cell("clip", "video", 300, 0),
      cell("memo", "note", 600, 0),
      cell("voice", "audio", 900, 0),
      cell("pending", "image", 1200, 0, { asset_id: undefined }),
    ]);
    expect(gallery).toEqual([
      { src: assetPreviewUrl("a-photo"), title: "photo" },
      { src: assetFileUrl("a-clip"), title: "clip", video: true },
    ]);
  });

  it("一行一行从上往下、行里从左往右 —— 手摆的一排上沿差几个像素也算同一行", () => {
    const gallery = boardPreviewGallery([
      cell("row2-left", "image", 0, 400),
      cell("row1-right", "image", 600, -6),
      cell("row1-mid", "image", 300, 9),
      cell("row1-left", "image", 0, 0),
    ]);
    expect(gallery.map((item) => item.title)).toEqual(["row1-left", "row1-mid", "row1-right", "row2-left"]);
  });

  it("没起名的用正文那一栏(和格子上显示的一样)", () => {
    expect(boardPreviewGallery([cell("x", "image", 0, 0, { title: undefined, text: "海边.png" })])[0].title).toBe("海边.png");
  });
});
