/** @vitest-environment jsdom */
/**
 * 画布上的线**什么时候会动**:动画(`canvas-edge-live`)只挂在「运行走过」的线上。
 *
 * 「运行走过」= 这条边的两头都进了流程(不是 `skipped`):跑完的和正在跑的,都算 —— 节点一侧
 * 只有这两档状态,没有更细的「当前这根边」。此前动画长在所有数据线上,画布没在跑时也一片在动,
 * 被维护者读成「正在跑 / 有东西流过来」。现在没在跑的时候,一根线都不动。
 */
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Edge } from "@xyflow/react";

import type { WorkflowGraph } from "@/api/client";

import { CANVAS_EDGE_TYPES } from "@/components/app/canvasEdgeShape";
import { canvasEdgeClass } from "@/components/app/canvasEdges";
import { WORKFLOW_CANVAS_EDGE_TYPES } from "@/features/workflows/ReferenceHintEdge";
import { REFERENCE_HINT_EDGE_TYPE } from "@/features/workflows/referenceHints";
import type { Step } from "@/features/workflows/runSteps";
import { canvasEdgeHeightRank, canvasEdgesForFlow, useWorkflowDisplayEdges } from "@/features/workflows/useWorkflowDisplayElements";
import type { WorkflowRunState } from "@/features/workflows/useWorkflowRun";

/** 一条数据线(静止的虚线)+ 一条普通控制线。 */
const edges: Edge[] = [
  { id: "d", source: "a", target: "b", className: canvasEdgeClass("data", { flow: true }), data: { kind: "data" } },
  { id: "c", source: "b", target: "c" },
];

const step = (nid: string, status: Step["status"]): Step => ({ nid, name: nid, status });

function shown(runByNode: WorkflowRunState["runByNode"]) {
  return renderHook(() => useWorkflowDisplayEdges(edges, runByNode, "default")).result.current;
}

it("没在跑:一根线都不动 —— 数据线还是那条静止的虚线", () => {
  const shownEdges = shown({});
  expect(shownEdges[0].className).toBe(canvasEdgeClass("data", { flow: true }));
  expect(shownEdges[0].className).not.toContain("canvas-edge-live");
  expect(shownEdges[1].className).toBeUndefined();
});

it("跑过 / 正在跑:那条边换成「运行走过」—— 虚线,而且在走", () => {
  //: 「正在跑」的那一步(b)和跑完的(a)都算走过:started 事件一到,这一步的状态就是 running。
  const shownEdges = shown({ a: step("a", "done"), b: step("b", "running") });
  expect(shownEdges[0].className).toBe(canvasEdgeClass("taken"));
  expect(shownEdges[0].className).toContain("canvas-edge-live");
  expect(shownEdges[0].className).toContain("canvas-edge-flow");
});

it("有一头没进流程(skipped):这根没走过,不动", () => {
  const shownEdges = shown({ a: step("a", "done"), c: step("c", "skipped") });
  expect(shownEdges.map((edge) => edge.className)).toEqual([canvasEdgeClass("data", { flow: true }), undefined]);
});

/**
 * 同一对节点之间的多条边**各走各的道**:交给 React Flow 之前先按「第几条」错开
 * (算法在 components/app/canvasEdgeShape,画出来的样子在那儿有 DOM 测试)。
 *
 * 这一层是**唯一能一起算的地方**:真连线(控制线 + 数据线)和画在这一对上的引用提示线分两处生成,
 * 分开贴道次的话两边都以为自己是独苗 —— 折边回来之后它们又会叠成一根。
 */
describe("同一对节点之间的多条边:交给 React Flow 之前先让开", () => {
  const hint: Edge = {
    id: "ref-hint:llm-1>out:text>set>in:template",
    source: "llm-1",
    target: "set",
    type: REFERENCE_HINT_EDGE_TYPE,
    data: { kind: REFERENCE_HINT_EDGE_TYPE },
  };

  it("控制线 + 数据线 + 这一对上的提示线:三条各走各的道,顺序只看 id", () => {
    const control: Edge = { id: "e-llm-1-set", source: "llm-1", target: "set" };
    const data: Edge = { id: "d-llm-1-text-set-template", source: "llm-1", target: "set", data: { kind: "data" } };
    const shown = canvasEdgesForFlow([hint], [control, data], { annotationMode: false });
    const laneOf = (id: string) => shown.find((edge) => edge.id === id)?.data?.lane;
    //: d… < e… < ref-hint…:三条道分别 -24 / 0 / +24(居中分布,见 parallelEdgeLane)。
    //: 正中那条(道次 0)**不贴道次** —— 贴上去的只有"让它让开"的那几条,0 就是"照老样子画"。
    expect(laneOf("d-llm-1-text-set-template")).toBe(-24);
    expect(laneOf("e-llm-1-set")).toBeUndefined();
    expect(laneOf(hint.id)).toBe(24);
    //: 提示线仍旧排在最前(先画,真连线压在上面),不因为贴了道次换位置。
    expect(shown.map((edge) => edge.id)).toEqual([hint.id, "e-llm-1-set", "d-llm-1-text-set-template"]);
  });

  it("只有一条连线时那条边原样:不动它的道次,可选中语义照旧", () => {
    const control: Edge = { id: "e-a-b", source: "a", target: "b" };
    const shown = canvasEdgesForFlow([], [control], { annotationMode: false });
    expect(shown).toEqual([{ ...control, selectable: true }]);
    expect(shown[0].data).toBeUndefined();
    expect(canvasEdgesForFlow([], [control], { annotationMode: true })[0].selectable).toBe(false);
  });

  it("两种走线方式都由共用的那个边组件画;提示线另有它的渲染器", () => {
    expect(WORKFLOW_CANVAS_EDGE_TYPES.default).toBe(CANVAS_EDGE_TYPES.default);
    expect(WORKFLOW_CANVAS_EDGE_TYPES.smoothstep).toBe(CANVAS_EDGE_TYPES.smoothstep);
    expect(WORKFLOW_CANVAS_EDGE_TYPES[REFERENCE_HINT_EDGE_TYPE]).toBeDefined();
  });

  /**
   * 道次的先后**必须跟着接点在卡片上的高低**:控制口在标题层(≈29),数据口在页脚(第一行 ≈78,
   * 往后每行 +19)。按 id 排的话,`d-…-prompt` < `d-…-template` < `e-…` —— 控制线拿到 +24(往下),
   * 页脚第一行的数据线拿到 -24(往上),49 的天然间隔撞上 48 的跨度,两根差 0.8px 就叠上了(实测)。
   */
  it("道次按天生高低排:控制线在最上面那道,页脚第一行在它下面 —— 谁也不插到谁身上", () => {
    const graph = {
      nodes: [
        { id: "llm-1", type: "llm", position: { x: 0, y: 0 }, config: {}, outputs: ["text"] },
        { id: "template-1", type: "template", position: { x: 460, y: 0 }, config: {}, inputs: ["template", "prompt"] },
      ],
      edges: [],
    } as unknown as WorkflowGraph;
    const heightOf = canvasEdgeHeightRank(graph, new Map());
    const control: Edge = { id: "e-llm-1-template-1", source: "llm-1", target: "template-1" };
    const firstRow: Edge = { id: "d-llm-1-text-template-1-template", source: "llm-1", target: "template-1", sourceHandle: "out:text", targetHandle: "in:template" };
    const secondRow: Edge = { id: "d-llm-1-text-template-1-prompt", source: "llm-1", target: "template-1", sourceHandle: "out:text", targetHandle: "in:prompt" };
    expect(heightOf(control)).toBeLessThan(heightOf(firstRow));
    expect(heightOf(firstRow)).toBeLessThan(heightOf(secondRow));

    const laneOf = (edge: Edge) =>
      canvasEdgesForFlow([], [control, firstRow, secondRow], { annotationMode: false, heightOf }).find((one) => one.id === edge.id)?.data?.lane;
    //: 控制线(-24)在最上面,页脚第一行(0)在中间,第二行(+24)在最下面。
    expect(laneOf(control)).toBe(-24);
    expect(laneOf(firstRow)).toBeUndefined(); //: 正中那条不动,不贴道次
    expect(laneOf(secondRow)).toBe(24);
  });
});
