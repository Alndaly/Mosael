import { describe, expect, it } from "vitest";
import type { Node } from "@xyflow/react";

import {
  canMoveComment,
  canPlaceCommentDraft,
  boardItems,
  focusBoardNode,
  toCanvas,
  moveCommentAnchorByScreenDelta,
  shouldDismissCommentOverlay,
  shouldSuppressCommentPlacement,
} from "./BoardCanvas";

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
  it("编辑中的评论可以从消息圆点按屏幕位移拖动，并保留节点锚定关系", () => {
    const anchor = { kind: "canvas" as const, x: 120, y: 80, node_id: "video-1" };
    const screenToFlowPosition = ({ x, y }: { x: number; y: number }) => ({ x: x / 2, y: y / 2 });

    expect(moveCommentAnchorByScreenDelta(
      anchor,
      { x: 200, y: 100 },
      { x: 260, y: 140 },
      screenToFlowPosition,
    )).toEqual({ kind: "canvas", x: 150, y: 100, node_id: "video-1" });
  });

  it("已有未发送评论时不允许点击画布迁移或重建评论卡", () => {
    expect(canPlaceCommentDraft(true, false)).toBe(true);
    expect(canPlaceCommentDraft(true, true)).toBe(false);
    expect(canPlaceCommentDraft(false, false)).toBe(false);
  });

  it("拖动画布或刚收起已有评论时不会在松手处创建评论", () => {
    expect(canPlaceCommentDraft(true, false, true, false)).toBe(false);
    expect(canPlaceCommentDraft(true, false, false, true)).toBe(false);
  });

  it("从已有评论内容拖到画布时不会把松手位置当成新评论落点", () => {
    expect(shouldSuppressCommentPlacement({
      moved: true,
      dismissedActive: false,
      startedInsideOverlay: true,
      endedInsideOverlay: false,
    })).toBe(true);
    expect(shouldSuppressCommentPlacement({
      moved: false,
      dismissedActive: false,
      startedInsideOverlay: true,
      endedInsideOverlay: true,
    })).toBe(false);
  });

  it("只有评论作者可以移动评论锚点", () => {
    expect(canMoveComment("author-1", "author-1")).toBe(true);
    expect(canMoveComment("author-1", "member-2")).toBe(false);
    expect(canMoveComment(null, "member-2")).toBe(false);
  });

  it("评论浮层仅在点击自身时保持，点击画布或应用其他区域都会收起", () => {
    expect(shouldDismissCommentOverlay(true, false, false)).toBe(true);
    expect(shouldDismissCommentOverlay(false, true, false)).toBe(true);
    expect(shouldDismissCommentOverlay(true, false, true)).toBe(false);
    expect(shouldDismissCommentOverlay(false, false, false)).toBe(false);
  });
});


describe("标记汇出", () => {
  it("标记不混进 items —— 它没有素材、不生成、连不了线", () => {
    const nodes = [
      { id: "note-1", type: "note", position: { x: 0, y: 0 }, data: { item: { id: "note-1", kind: "note", x: 0, y: 0 } } },
      // 拖过之后位置以 React Flow 为准:汇出时要读节点的 position,而不是 data 里那份旧的。
      { id: "marker:m1", type: "marker", position: { x: 320.4, y: -40.6 }, data: { marker: { id: "m1", name: "分镜起点", x: 0, y: 0, shortcut: "Alt+1" } } },
    ] as unknown as Node[];

    const canvas = toCanvas(nodes, []);
    expect(canvas.items.map((one) => one.id)).toEqual(["note-1"]);
    expect(canvas.markers).toEqual([{ id: "m1", name: "分镜起点", x: 320, y: -41, shortcut: "Alt+1" }]);
  });
});

describe("画板项的派生", () => {
  it("跳过标记 —— 它没有 item,读下去当场抛", () => {
    // 这条钉的是一次真崩溃:加了标记之后,`nodes.map(n => n.data.item).filter(i => i.kind === …)`
    // 在标记那一项上读到 undefined,`.kind` 抛在派生里 = 整张画板白屏。加标记就打不开画板了。
    const nodes = [
      { id: "note-1", type: "note", position: { x: 0, y: 0 }, data: { item: { id: "note-1", kind: "note", x: 0, y: 0 } } },
      { id: "marker:m1", type: "marker", position: { x: 0, y: 0 }, data: { marker: { id: "m1", name: "起点", x: 0, y: 0 } } },
    ] as unknown as Node[];

    expect(() => boardItems(nodes).filter((item) => item.kind === "document")).not.toThrow();
    expect(boardItems(nodes).map((item) => item.id)).toEqual(["note-1"]);
  });
});
