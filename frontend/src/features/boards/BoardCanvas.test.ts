import { describe, expect, it } from "vitest";
import type { Node } from "@xyflow/react";

import { canPlaceCommentDraft, focusBoardNode } from "./BoardCanvas";

describe("画板节点聚焦", () => {
  it("一次点击就只选中目标节点", () => {
    const nodes = [
      { id: "old", selected: true },
      { id: "target", selected: false },
    ] as Node[];

    expect(focusBoardNode(nodes, "target").map((node) => [node.id, node.selected])).toEqual([
      ["old", false],
      ["target", true],
    ]);
  });

  it("目标已选中时保持对象稳定", () => {
    const target = { id: "target", selected: true } as Node;
    expect(focusBoardNode([target], "target")[0]).toBe(target);
  });
});

describe("画布评论落点", () => {
  it("已有未发送评论时不允许点击画布迁移或重建评论卡", () => {
    expect(canPlaceCommentDraft(true, false)).toBe(true);
    expect(canPlaceCommentDraft(true, true)).toBe(false);
    expect(canPlaceCommentDraft(false, false)).toBe(false);
  });
});
