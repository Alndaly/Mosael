import { describe, expect, it } from "vitest";

import { anchorToNode } from "./WorkflowsView";

/** 最小 ReactFlow 实例替身:只用到 getNode 与 flowToScreenPosition。 */
function fakeInstance(node: { x: number; y: number; w: number; h: number } | null) {
  return {
    getNode: () => (node ? { position: { x: node.x, y: node.y }, measured: { width: node.w, height: node.h } } : undefined),
    // 视口 1:1 且无偏移:流坐标即屏幕坐标,把测试聚焦在摆放逻辑本身。
    flowToScreenPosition: (p: { x: number; y: number }) => p,
  } as never;
}

const VIEW = { width: 1200, height: 800 };

describe("anchorToNode", () => {
  it("默认贴节点右侧", () => {
    const a = anchorToNode(fakeInstance({ x: 100, y: 200, w: 200, h: 60 }), "n", VIEW)!;
    expect(a.left).toBe(300 + 10); // 节点右缘 + gap
    expect(a.top).toBe(200);
  });

  it("右边放不下就翻到左侧", () => {
    // 节点右缘 1000,右侧需要 10+320=330 → 1330 > 1200-12,放不下
    const a = anchorToNode(fakeInstance({ x: 800, y: 100, w: 200, h: 60 }), "n", VIEW)!;
    expect(a.left).toBe(800 - 10 - 320); // 翻到左侧
  });

  it("左右都放不下时落到节点下方", () => {
    // 节点几乎占满宽度:两侧都塞不进 320
    const a = anchorToNode(fakeInstance({ x: 20, y: 100, w: 1100, h: 60 }), "n", VIEW)!;
    expect(a.top).toBeGreaterThan(160); // 在节点下缘之下
    expect(a.left).toBeGreaterThanOrEqual(12);
    expect(a.left + 320).toBeLessThanOrEqual(VIEW.width - 12);
  });

  it("始终夹在窗口内(节点在视口外也不会把面板甩出去)", () => {
    for (const pos of [{ x: -5000, y: -5000 }, { x: 9000, y: 9000 }]) {
      const a = anchorToNode(fakeInstance({ ...pos, w: 200, h: 60 }), "n", VIEW)!;
      expect(a.left).toBeGreaterThanOrEqual(12);
      expect(a.left + 320).toBeLessThanOrEqual(VIEW.width - 12 + 1);
      expect(a.top).toBeGreaterThanOrEqual(12);
      expect(a.top + a.maxHeight).toBeLessThanOrEqual(VIEW.height - 12 + 1);
    }
  });

  it("窗口很矮时高度封顶随之收缩", () => {
    const a = anchorToNode(fakeInstance({ x: 100, y: 100, w: 200, h: 60 }), "n", { ...VIEW, height: 300 })!;
    expect(a.maxHeight).toBe(300 - 24);
  });

  it("没有实例或没有节点时不给位置", () => {
    expect(anchorToNode(null, "n", VIEW)).toBeNull();
    expect(anchorToNode(fakeInstance({ x: 0, y: 0, w: 1, h: 1 }), null, VIEW)).toBeNull();
    expect(anchorToNode(fakeInstance(null), "missing", VIEW)).toBeNull();
  });
});
