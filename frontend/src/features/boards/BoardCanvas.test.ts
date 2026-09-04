import { describe, expect, it } from "vitest";
import type { Node } from "@xyflow/react";

import { canMoveComment, canPlaceCommentDraft, focusBoardNode } from "./BoardCanvas";

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

  it("拖动画布或刚收起已有评论时不会在松手处创建评论", () => {
    expect(canPlaceCommentDraft(true, false, true, false)).toBe(false);
    expect(canPlaceCommentDraft(true, false, false, true)).toBe(false);
  });

  it("只有评论作者可以移动评论锚点", () => {
    expect(canMoveComment("author-1", "author-1")).toBe(true);
    expect(canMoveComment("author-1", "member-2")).toBe(false);
    expect(canMoveComment(null, "member-2")).toBe(false);
  });
});
