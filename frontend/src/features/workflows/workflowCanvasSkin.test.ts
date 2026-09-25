import { describe, expect, it } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { CANVAS_EDGE_MARKER } from "@/components/app/canvasEdgeShape";
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

/** 皮肤里给某个语义类设的 `--xy-edge-stroke`(没有就是 undefined)。 */
function strokeFor(className: string): string | undefined {
  const escaped = className.replace(/\./g, "\\.");
  return WORKFLOW_CANVAS_CLASS.match(new RegExp(`\\[&_\\.${escaped}\\]:\\[--xy-edge-stroke:([^\\]]+)\\]`))?.[1];
}

describe("工作流画布皮肤 ↔ 连线模型", () => {
  it("模型挂到边上的每个语义类,皮肤里都有一条按它上色的规则", () => {
    const semantic = edges.flatMap((edge) => (edge.className ?? "").split(/\s+/)).filter((one) => one.startsWith("wf-edge-"));
    expect(new Set(semantic)).toEqual(new Set(["wf-edge-true", "wf-edge-false", "wf-edge-data"]));
    for (const one of semantic) expect(strokeFor(one), one).toBeDefined();
  });

  it("真绿、假红、数据线主色、类型不匹配警示色 —— 全经 xyflow 的线色变量", () => {
    expect(strokeFor("wf-edge-true")).toBe("var(--success)");
    expect(strokeFor("wf-edge-false")).toBe("var(--destructive)");
    expect(strokeFor("wf-edge-data")).toBe("var(--primary)");
    expect(strokeFor("wf-edge-data.wf-edge-mismatch")).toBe("var(--warning)");
    // 直接写 stroke 颜色的话,选中态读的 --xy-edge-stroke-selected 就接不上了。
    expect(WORKFLOW_CANVAS_CLASS).not.toMatch(/:stroke-|\[stroke:/);
  });

  it("分支线的箭头和线同色;普通控制线不写 markerEnd,留给 defaultEdgeOptions 的默认箭头", () => {
    expect(byId("t").markerEnd).toEqual({ ...CANVAS_EDGE_MARKER, color: "var(--success)" });
    expect(byId("f").markerEnd).toEqual({ ...CANVAS_EDGE_MARKER, color: "var(--destructive)" });
    // `markerEnd: undefined` 也会盖掉默认值(React Flow 是 { ...defaultEdgeOptions, ...edge })—— 键本身不能在。
    expect("markerEnd" in byId("c")).toBe(false);
  });

  it("接点样式不再靠 `!` 硬压 React Flow —— 它在 vendor 层,工具类本来就赢", () => {
    expect(WORKFLOW_HANDLE_CLASS).not.toMatch(/!(\s|$)/);
    expect(WORKFLOW_HANDLE_CLASS).toContain(String.raw`[&.react-flow\_\_handle-left:hover]`);
  });
});
