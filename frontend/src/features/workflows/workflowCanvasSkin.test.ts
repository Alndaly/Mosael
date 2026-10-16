import { describe, expect, it } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { CANVAS_EDGE_CLASS, canvasEdgeClass } from "@/components/app/canvasEdges";
import { toWorkflowFlowEdges } from "@/features/workflows/workflowCanvasModel";
import { WORKFLOW_CANVAS_CLASS, WORKFLOW_HANDLE_CLASS } from "@/features/workflows/workflowCanvasSkin";

const t = ((key: MessageKey) => key) as (key: MessageKey) => string;

const graph: WorkflowGraph = {
  nodes: [
    { id: "cond", type: "condition" },
    { id: "yes", type: "llm" },
    { id: "no", type: "llm" },
    { id: "after", type: "llm" },
  ],
  edges: [
    { id: "t", source: "cond", target: "yes", source_handle: "true" },
    { id: "f", source: "cond", target: "no", source_handle: "false" },
    { id: "c", source: "yes", target: "after" },
    { id: "d", source: "yes", target: "after", kind: "data", source_output: "text", target_input: "prompt" },
  ],
};

const edges = toWorkflowFlowEdges(graph, t, new Map());
const byId = (id: string) => edges.find((edge) => edge.id === id)!;

/** 共用那串里给某个类设的 `--xy-edge-stroke`(没有就是 undefined)。 */
function strokeFor(className: string): string | undefined {
  return CANVAS_EDGE_CLASS.match(new RegExp(`\\[&_\\.${className}\\]:\\[--xy-edge-stroke:([^\\]]+)\\]`))?.[1];
}

describe("工作流的连线 ↔ 共用的连线外观(components/app/canvasEdges)", () => {
  it("模型挂到边上的每个类,共用那串里都有规则 —— 颜色类有线色,flow 有静止的虚线、没有动画", () => {
    const classes = edges.flatMap((edge) => (edge.className ?? "").split(/\s+/)).filter(Boolean);
    expect(new Set(classes)).toEqual(new Set(["canvas-edge-true", "canvas-edge-false", "canvas-edge-data", "canvas-edge-flow"]));
    for (const one of classes.filter((name) => name !== "canvas-edge-flow")) expect(strokeFor(one), one).toBeDefined();
    expect(CANVAS_EDGE_CLASS).toContain(String.raw`[&_.canvas-edge-flow_.react-flow\_\_edge-path]:[stroke-dasharray:`);
    //: **数据线不流动。** 动画那一支叫 canvas-edge-live,只挂在「运行走过」上(见 canvasEdges 的表)。
    expect(CANVAS_EDGE_CLASS).not.toMatch(/canvas-edge-flow[^ ]*motion-safe:animate/);
  });

  it("条件分支是真/假那一种,数据线是数据那一种、静止虚线,普通控制线不挂类", () => {
    expect(byId("t").className).toBe(canvasEdgeClass("true"));
    expect(byId("f").className).toBe(canvasEdgeClass("false"));
    expect(byId("d").className).toBe(canvasEdgeClass("data", { flow: true }));
    //: 没在跑的时候画布上一条都不许动:数据线的类里没有 live。
    expect(byId("d").className).not.toContain("canvas-edge-live");
    expect(byId("c").className).toBeUndefined();
  });

  it("控制线(含分支)都不写 markerEnd,用 defaultEdgeOptions 那一个;数据线显式不要箭头", () => {
    //: 分支不再各造一个彩色箭头 —— 共用的那个取线自己的颜色(context-stroke)。
    for (const id of ["t", "f", "c"]) expect("markerEnd" in byId(id), id).toBe(false);
    //: `markerEnd: undefined` 才盖得掉默认值(React Flow 是 { ...defaultEdgeOptions, ...edge })。
    expect("markerEnd" in byId("d")).toBe(true);
    expect(byId("d").markerEnd).toBeUndefined();
    //: 数据线的虚线由 canvas-edge-flow 给(它是形状,不是动画);会走的那一支只在「运行走过」的线上,
    //: React Flow 自己那套 animated 两处都不用(两套虚线节奏会打架)。
    expect(byId("d").animated).toBeUndefined();
  });

  it("工作流自己的皮肤里不再有连线的规则 —— 线只有一套", () => {
    expect(WORKFLOW_CANVAS_CLASS).not.toMatch(/edge|--xy-connectionline/);
  });

  it("接点样式不再靠 `!` 硬压 React Flow —— 它在 vendor 层,工具类本来就赢", () => {
    expect(WORKFLOW_HANDLE_CLASS).not.toMatch(/!(\s|$)/);
    expect(WORKFLOW_HANDLE_CLASS).toContain(String.raw`[&.react-flow\_\_handle-left:hover]`);
  });
});
