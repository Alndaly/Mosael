import { describe, expect, it } from "vitest";

import { anchorToNode } from "./WorkflowsView";

/**
 * 贴节点浮现的检查器,**四条边都不能出问题**。
 *
 * 这里钉的是一次真事:面板的 CSS 是 `w-[380px]`,而摆放计算按 320 算(旁边还留着一句
 * 「380 而不是 320」的注释,说明宽度改过、常量没跟着改)。60px 的错位把四条边一起弄坏了 ——
 * 右侧溢出被切、左翻时**压住自己的节点**、上下因为拿"高度上限"当"实际高度"而被顶出窗口。
 *
 * 所以这些用例断言的是**不变量**(不出窗口、不盖住自己),而不是具体像素:写死像素的测试
 * 正是当初没拦住这个 bug 的原因 —— 它把错误的常量一起抄了进去。
 */

const PANEL_W = 380;
const MARGIN = 12;

const fakeInstance = {
  // 视口 1:1 且无偏移:流坐标即屏幕坐标,把测试聚焦在摆放逻辑本身。
  flowToScreenPosition: (p: { x: number; y: number }) => p,
} as never;

function node(n: { x: number; y: number; w: number; h: number }) {
  return { position: { x: n.x, y: n.y }, measured: { width: n.w, height: n.h } } as never;
}

const VIEW = { width: 1200, height: 800 };

/** 面板和它自己那个节点有没有重叠。 */
function overlapsNode(
  a: { left: number; top: number; maxHeight: number },
  n: { x: number; y: number; w: number; h: number },
  panelH = a.maxHeight,
) {
  return a.left < n.x + n.w && a.left + PANEL_W > n.x && a.top < n.y + n.h && a.top + panelH > n.y;
}

function insideViewport(a: { left: number; top: number; maxHeight: number }, panelH = a.maxHeight) {
  return (
    a.left >= MARGIN - 0.5 &&
    a.left + PANEL_W <= VIEW.width - MARGIN + 0.5 &&
    a.top >= MARGIN - 0.5 &&
    a.top + panelH <= VIEW.height - MARGIN + 0.5
  );
}

describe("anchorToNode 的四条边", () => {
  //: 覆盖各种位置和尺寸:贴边、超出视口、宽得离谱、矮的和高的面板。
  const nodes = [
    { x: 100, y: 200, w: 200, h: 60 },
    { x: 800, y: 100, w: 200, h: 60 },
    { x: 20, y: 100, w: 1100, h: 60 },
    { x: 20, y: 300, w: 1100, h: 60 },
    { x: 1150, y: 60, w: 200, h: 60 },
    { x: -80, y: 700, w: 200, h: 60 },
    { x: 500, y: 760, w: 200, h: 60 },
    { x: 500, y: -40, w: 200, h: 60 },
    { x: 10, y: 10, w: 1180, h: 780 },
  ];

  for (const panelH of [200, 560]) {
    for (const n of nodes) {
      it(`不出窗口:节点 ${n.x},${n.y} ${n.w}×${n.h} / 面板高 ${panelH}`, () => {
        const a = anchorToNode(fakeInstance, node(n), VIEW, panelH)!;
        expect(insideViewport(a, Math.min(panelH, a.maxHeight))).toBe(true);
      });
    }
  }

  for (const n of nodes.slice(0, 8)) {
    it(`不盖住自己那个节点:${n.x},${n.y} ${n.w}×${n.h}`, () => {
      // 盖住画布上**别的**节点没办法(到处都是节点),盖住自己不行 ——
      // 用户正是为了看这个节点才点开它的。
      const a = anchorToNode(fakeInstance, node(n), VIEW, 200)!;
      expect(overlapsNode(a, n, 200)).toBe(false);
    });
  }

  it("节点大到占满窗口时,贴着最宽的那一边放", () => {
    // 四个方向都躲不开,只能挡住一部分 —— 但要挡在边上,不是正中间。
    const n = { x: 10, y: 10, w: 1180, h: 780 };
    const a = anchorToNode(fakeInstance, node(n), VIEW, 200)!;
    expect(insideViewport(a, 200)).toBe(true);
  });

  it("首选右侧", () => {
    const n = { x: 100, y: 200, w: 200, h: 60 };
    const a = anchorToNode(fakeInstance, node(n), VIEW, 200)!;
    expect(a.left).toBe(n.x + n.w + 10);
    expect(a.top).toBe(n.y);
  });

  it("右边放不下就翻到左侧,而且用的是**真实宽度**", () => {
    // 按 320 算的话左翻位置会偏右 60px,正好压在节点身上 —— 这就是那个 bug。
    const n = { x: 800, y: 100, w: 200, h: 60 };
    const a = anchorToNode(fakeInstance, node(n), VIEW, 200)!;
    expect(a.left).toBe(n.x - 10 - PANEL_W);
    expect(overlapsNode(a, n, 200)).toBe(false);
  });

  it("矮面板不该被当成高面板往上顶", () => {
    // 竖直钳制此前拿 maxHeight(上限 560)当实际高度用:面板只有 200 高时被硬推到
    // viewH-572 以上,顶到工具条上去。
    const n = { x: 20, y: 600, w: 1100, h: 60 };
    const a = anchorToNode(fakeInstance, node(n), VIEW, 200)!;
    expect(a.top + 200).toBeLessThanOrEqual(VIEW.height - MARGIN + 0.5);
    expect(overlapsNode(a, n, 200)).toBe(false);
  });

  it("窗口很矮时高度封顶随之收缩", () => {
    const a = anchorToNode(fakeInstance, node({ x: 100, y: 100, w: 200, h: 60 }), { width: 1200, height: 300 })!;
    expect(a.maxHeight).toBeLessThanOrEqual(300 - MARGIN * 2);
  });

  it("没有实例或没有节点时不给位置", () => {
    expect(anchorToNode(null, node({ x: 0, y: 0, w: 1, h: 1 }), VIEW)).toBeNull();
    expect(anchorToNode(fakeInstance, null, VIEW)).toBeNull();
  });
});
