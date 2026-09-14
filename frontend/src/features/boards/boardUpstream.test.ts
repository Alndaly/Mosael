import { describe, expect, it } from "vitest";

import type { BoardItem } from "@/api/client";

import { upstreamOf } from "./boardUpstream";

const note = (id: string, text: string) => ({ id, kind: "note", text }) as unknown as BoardItem;
const image = (id: string, assetId: string) => ({ id, kind: "image", asset_id: assetId }) as unknown as BoardItem;
const edge = (source: string, target: string) => ({ source, target });

describe("下游从上游拿到什么", () => {
  it("便签给的是提示词,不是参考图", () => {
    // 一张写着描述的便签连到图片节点上,用户的意思是「照这段话画」—— 它根本没有图。
    const up = upstreamOf("img", [note("n1", "一只绿梨"), image("img", "")], [edge("n1", "img")], new Map());
    expect(up.texts.map((one) => one.text)).toEqual(["一只绿梨"]);
    expect(up.assets).toEqual([]);
  });

  it("上游的图当参考素材", () => {
    const up = upstreamOf("img2", [image("img1", "a1"), image("img2", "")], [edge("img1", "img2")], new Map());
    expect(up.assets.map((one) => one.assetId)).toEqual(["a1"]);
  });

  it("只认连到自己身上的那些,方向反了不算", () => {
    const items = [note("n1", "上游"), note("n2", "下游"), note("n3", "旁边的")];
    // n1 → n2,而 n2 → n3:算 n2 的上游时只有 n1,n3 是它的下游。
    const up = upstreamOf("n2", items, [edge("n1", "n2"), edge("n2", "n3")], new Map());
    expect(up.texts.map((one) => one.itemId)).toEqual(["n1"]);
  });

  it("改了上游的字,重算一次就跟着变", () => {
    // 判定里那句「连线后改上游,下游要跟随」。这里不存快照,所以同一条连线喂不同的 items
    // 就该得到不同的结果 —— 组件里每次渲染都这么算一遍。
    const edges = [edge("n1", "img")];
    const before = upstreamOf("img", [note("n1", "一只绿梨"), image("img", "")], edges, new Map());
    const after = upstreamOf("img", [note("n1", "一只红苹果"), image("img", "")], edges, new Map());
    expect(before.texts[0].text).toBe("一只绿梨");
    expect(after.texts[0].text).toBe("一只红苹果");
  });

  it("没有连线时什么都不给", () => {
    const up = upstreamOf("img", [note("n1", "孤零零"), image("img", "")], [], new Map());
    expect(up).toEqual({ assets: [], texts: [], references: [], blocked: false, pending: false });
  });
});
