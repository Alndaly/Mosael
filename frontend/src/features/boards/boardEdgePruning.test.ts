import type { Edge, Node } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { toCanvas } from "./BoardCanvas";
import type { BoardItem } from "@/api/client";

/**
 * **一根悬空的线会让整张画板存不下去。**
 *
 * 后端校验「连线两端必须都是画板上的项」(domain/boards.py),而它拒的是**整次保存** ——
 * 用户看到的是「画板没能保存」,画面上那个被删掉的节点早就不见了,根本联想不到是它。
 *
 * 工具条那颗垃圾桶此前只 `filter` 节点、不动 edges,于是删掉一个连着线的节点之后,
 * 这张画板就再也存不上了。键盘删除走 React Flow 自己的 deleteElements,一直是连线一起删的
 * —— 所以这个毛病只在那颗按钮上,也因此更难被发现。
 */
const item = (id: string): Node => ({
  id,
  type: "image",
  position: { x: 0, y: 0 },
  data: { item: { id, kind: "image" } as unknown as BoardItem },
});
const marker = (id: string): Node => ({
  id: `marker:${id}`,
  type: "marker",
  position: { x: 0, y: 0 },
  data: { marker: { id, name: "", x: 0, y: 0 } },
});
const edge = (source: string, target: string): Edge => ({ id: `${source}->${target}`, source, target });

describe("保存时不放出悬空的线", () => {
  it("两端都在,就照原样存下去", () => {
    const canvas = toCanvas([item("a"), item("b")], [edge("a", "b")]);
    expect(canvas.edges).toEqual([{ id: "a->b", source: "a", target: "b" }]);
  });

  it("一端已经不在了,这根线就不进 payload", () => {
    // 后端会因为它拒掉**整次**保存,而不是忽略这一根。
    const canvas = toCanvas([item("a")], [edge("a", "gone"), edge("gone", "a")]);
    expect(canvas.edges).toEqual([]);
  });

  it("标记不算画板上的项 —— 连到标记上的线同样不算数", () => {
    // 标记是 React Flow 节点,但它进的是 markers 那一份,不进 items;后端只拿 items 校验。
    const canvas = toCanvas([item("a"), marker("m1")], [edge("a", "marker:m1")]);
    expect(canvas.markers).toHaveLength(1);
    expect(canvas.edges).toEqual([]);
  });
});
