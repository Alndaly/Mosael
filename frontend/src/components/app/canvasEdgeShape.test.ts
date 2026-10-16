/**
 * 同一对节点之间的多条边怎么让开 —— **算的那一半**(画出来的那一半见 canvasEdgeShape.dom.test)。
 *
 * 规范化拿掉「同一对节点间的控制边」那道折边之后,一对节点上会同时挂着「实线顺序」和「虚线值」两根线:
 * 模板里被折掉的 68 对会一起回来,加上现在已经并存的 17 对,以及 20 对 2–3 条的数据边。React Flow
 * 不做平行边错开 —— 两根在中段重合,看着像一根粗线。这里定的是:一对节点一组、组内第几条让开多少。
 *
 * 三条不能丢的性质:
 *  · **单条边一个像素都不动。** 老图、老测试、老观感都不该因为这件事变一点点。
 *  · **序号要稳定。** 同一份图每次渲染算出来是同一个序(按边的 id 排,不看数组顺序、不看对象身份),
 *    否则线会在两次渲染之间跳。
 *  · **两头钉在接点上。** 让开的只有中段:起点终点还是那两个接点,线不会从卡片上脱开。
 */
import { getBezierPath, getSmoothStepPath, Position } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import {
  CANVAS_PARALLEL_EDGE_GAP,
  CANVAS_PARALLEL_EDGE_SPAN,
  canvasEdgePath,
  laneEdges,
  parallelEdgeLane,
  parallelEdgeLanes,
  type CanvasEdgeEnds,
} from "@/components/app/canvasEdgeShape";

/** 一条边在道次这件事上要看的东西(真边缘上还带着 data:道次就贴在那儿)。 */
type LaneEdge = { id: string; source: string; target: string; data?: Record<string, unknown> };
const edge = (id: string, source = "a", target = "b"): LaneEdge => ({ id, source, target });

/** 贝塞尔 `d` 里中段那一点(t = 0.5)的 y:三次贝塞尔在 0.5 处的权重是 1/8、3/8、3/8、1/8。 */
function midY(path: string): number {
  const found = /^M([-\d.]+),([-\d.]+) C([-\d.]+),([-\d.]+) ([-\d.]+),([-\d.]+) ([-\d.]+),([-\d.]+)$/.exec(path);
  if (!found) throw new Error(`不是贝塞尔的 d:${path}`);
  const [, , sy, , c1y, , c2y, , ty] = found;
  return (Number(sy) + 3 * Number(c1y) + 3 * Number(c2y) + Number(ty)) / 8;
}

/** 贝塞尔 `d` 里中段那一点的 x。 */
function midX(path: string): number {
  const found = /^M([-\d.]+),([-\d.]+) C([-\d.]+),([-\d.]+) ([-\d.]+),([-\d.]+) ([-\d.]+),([-\d.]+)$/.exec(path);
  if (!found) throw new Error(`不是贝塞尔的 d:${path}`);
  const [, sx, , c1x, , c2x, , tx] = found;
  return (Number(sx) + 3 * Number(c1x) + 3 * Number(c2x) + Number(tx)) / 8;
}

const ends = (over: Partial<CanvasEdgeEnds> = {}): CanvasEdgeEnds => ({
  sourceX: 160,
  sourceY: 25,
  sourcePosition: Position.Right,
  targetX: 400,
  targetY: 25,
  targetPosition: Position.Left,
  ...over,
});

describe("一对节点之间:我在第几条", () => {
  it("单条不让开 —— 那条边连引用都不换,画出来和以前一模一样", () => {
    const edges = [edge("e-a-b")];
    expect(parallelEdgeLanes(edges).size).toBe(0);
    expect(parallelEdgeLane(0, 1)).toBe(0);
    expect(laneEdges(edges)[0]).toBe(edges[0]);
  });

  it("两条:一上一下,各离中线半格", () => {
    const edges = [edge("d-a-text-b-template"), edge("e-a-b")];
    const lanes = parallelEdgeLanes(edges);
    expect(lanes.get("d-a-text-b-template")).toBe(-CANVAS_PARALLEL_EDGE_GAP / 2);
    expect(lanes.get("e-a-b")).toBe(CANVAS_PARALLEL_EDGE_GAP / 2);
    expect([0, 1].map((index) => parallelEdgeLane(index, 2))).toEqual([-12, 12]);
  });

  it("三条:中间那条在 0 —— 它的边对象原样不动,让开的是两侧那两条", () => {
    const edges = [edge("b-mid"), edge("a-left"), edge("c-right")];
    const lanes = parallelEdgeLanes(edges);
    expect([lanes.get("a-left"), lanes.get("b-mid"), lanes.get("c-right")]).toEqual([-24, 0, 24]);
    const shown = laneEdges(edges);
    expect(shown[0]).toBe(edges[0]);
    expect(shown[1]).not.toBe(edges[1]);
    expect(shown[1].data).toEqual({ lane: -24 });
  });

  it("道次的先后看天生高低:高的分上面那道,低的往下 —— 两根的间距只会变大", () => {
    //: 两条数据线天然差 19px(页脚相邻两行),但 id 的顺序正好反着(prompt < template,行号却是 template 在前)。
    const low = edge("d-a-text-b-template"); // 页脚第 0 行
    const high = edge("d-a-text-b-prompt"); // 页脚第 1 行
    const heightOf = (one: { id: string }) => (one.id.endsWith("prompt") ? 1 : 0);
    //: 按 id 排(不给高低):prompt(-12) 反而跑到 template(+12) 上面去了 —— 两根插到一起(19 - 24 = -5)。
    expect(parallelEdgeLanes([low, high]).get("d-a-text-b-template")).toBe(12);
    //: 按天生高低排:第 1 行往下、第 0 行往上,间距 19 + 24 = 43。
    const lanes = parallelEdgeLanes([low, high], heightOf);
    expect(lanes.get("d-a-text-b-template")).toBe(-12);
    expect(lanes.get("d-a-text-b-prompt")).toBe(12);
    //: 高低一样时仍旧按 id 断平(稳定)。
    expect(parallelEdgeLanes([low, high], () => 0)).toEqual(parallelEdgeLanes([low, high]));
  });

  it("序号只由 id 定:数组顺序、对象身份都不影响(线才不跳)", () => {
    const first = [...parallelEdgeLanes([edge("d-1"), edge("e-1"), edge("d-0")])].sort();
    const shuffled = [...parallelEdgeLanes([{ ...edge("e-1") }, { ...edge("d-0") }, { ...edge("d-1") }])].sort();
    expect(shuffled).toEqual(first);
  });

  it("同一份图反复算,道次一模一样", () => {
    const graph = () => [edge("e-b"), edge("d-a"), edge("d-c")];
    expect([...parallelEdgeLanes(graph())]).toEqual([...parallelEdgeLanes(graph())]);
    //: 边是每次新建的对象:序号不许跟对象身份有关(否则每渲染一次就换一次道)。
    expect([...parallelEdgeLanes(graph())]).toEqual([...parallelEdgeLanes(graph())]);
  });

  it("不同的一对节点各算各的;反向那一对(b→a)是另一对", () => {
    const lanes = parallelEdgeLanes([edge("x", "a", "b"), edge("y", "c", "d"), edge("z", "b", "a")]);
    expect(lanes.size).toBe(0);
  });

  it("再多条也不无限往外扩:总跨度封顶,道次仍各不相同", () => {
    const lanes = [0, 1, 2, 3, 4, 5, 6, 7].map((index) => parallelEdgeLane(index, 8));
    expect(Math.max(...lanes) - Math.min(...lanes)).toBeLessThanOrEqual(CANVAS_PARALLEL_EDGE_SPAN);
    expect(new Set(lanes).size).toBe(8);
    //: 到第 3 条才顶到上限:在那之前相邻两条正好一个 gap。
    expect(parallelEdgeLane(1, 3) - parallelEdgeLane(0, 3)).toBe(CANVAS_PARALLEL_EDGE_GAP);
    expect(parallelEdgeLane(1, 5) - parallelEdgeLane(0, 5)).toBe(CANVAS_PARALLEL_EDGE_SPAN / 4);
  });
});

describe("一条边怎么走", () => {
  it("不让开的那条(单条、或三条里的中间那条):就是 React Flow 内置那两种,逐字相同", () => {
    for (const shape of ["default", "smoothstep"] as const) {
      const builtin = shape === "smoothstep" ? getSmoothStepPath(ends()) : getBezierPath(ends());
      const ours = canvasEdgePath(shape, ends(), 0);
      expect(ours[0], shape).toBe(builtin[0]);
      expect([ours[1], ours[2]], shape).toEqual([builtin[1], builtin[2]]);
    }
  });

  it("贝塞尔让开:两头端点一个像素不动,中段整好挪 lane", () => {
    const base = canvasEdgePath("default", ends(), 0)[0];
    const moved = canvasEdgePath("default", ends(), 12)[0];
    expect(moved).not.toBe(base);
    expect(moved.startsWith("M160,25")).toBe(true);
    expect(moved.endsWith("400,25")).toBe(true);
    expect(midY(base)).toBe(25);
    //: 三次贝塞尔在 t=0.5 只走出控制点位移的 3/4 —— 控制点补上这个系数,中段才是整好一个 lane。
    expect(midY(moved)).toBeCloseTo(25 + 12, 9);
  });

  it("贝塞尔让开:竖直的一对往横里让(让开的是连线的垂直方向,不是画布的上下)", () => {
    const vertical = ends({ sourceX: 100, sourceY: 60, sourcePosition: Position.Bottom, targetX: 100, targetY: 300, targetPosition: Position.Top });
    const base = canvasEdgePath("default", vertical, 0)[0];
    const moved = canvasEdgePath("default", vertical, 12)[0];
    //: 横着挪满一个 lane(lane 的正方向是连线的右手边,屏幕坐标下 y 朝下),纵向一点不动。
    expect(midX(moved) - midX(base)).toBeCloseTo(-12, 9);
    expect(midY(moved)).toBeCloseTo(midY(base), 9);
    expect(midY(base)).toBeCloseTo(180, 9);
  });

  it("平滑折线让开:两头端点不动,中段那一横段整段挪 lane", () => {
    const base = canvasEdgePath("smoothstep", ends(), 0)[0];
    const moved = canvasEdgePath("smoothstep", ends(), 12)[0];
    expect(moved).not.toBe(base);
    expect(moved.startsWith("M160 25")).toBe(true);
    expect(moved.endsWith("L400 25")).toBe(true);
    //: 中段一横在 25 + 12 上(直连的那条整条都在 y = 25,碰不到 37)。
    expect(moved).toContain(",37");
    expect(base).not.toContain(",37");
  });
});
