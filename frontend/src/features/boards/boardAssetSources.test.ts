import { expect, it } from "vitest";
import type { BoardItem } from "@/api/domains/boards";
import { boardAssetSources } from "./boardAssetSources";
import { autoAssign } from "./NodeComposer";
const item = (kind: BoardItem["kind"], asset_id?: string): BoardItem => ({
  id: kind,
  kind,
  asset_id,
  x: 0,
  y: 0,
});
it("feeds a scene frame into image reference and video first-frame slots", () => {
  const sources = boardAssetSources([item("scene", "render")]);
  expect(sources).toEqual([{ assetId: "render", kind: "image", itemId: "scene" }]);
  //: 顺着线挂上的记着是从哪一格来的 —— 线断了,服务端存的时候凭它摘掉。
  expect(autoAssign([{ role: "reference_image", limit: 1 }], sources)).toEqual([
    { role: "reference_image", assetId: "render", from: "scene" },
  ]);
  expect(autoAssign([{ role: "first_frame", limit: 1 }], sources)).toEqual([
    { role: "first_frame", assetId: "render", from: "scene" },
  ]);
});
it("preserves input order without duplicating a scene frame also connected as an image", () => {
  expect(
    boardAssetSources([
      item("scene", "frame"),
      item("image", "frame"),
      item("video", "motion"),
      item("document", "invalid"),
      item("scene"),
    ]),
  ).toEqual([
    { assetId: "frame", kind: "image", itemId: "scene" },
    { assetId: "motion", kind: "video", itemId: "video" },
  ]);
});
