/** @vitest-environment jsdom */
/**
 * 编辑器把 `{{…}}` 引用画成提示线:主流程、循环体里都画;被引用的没接进流程时,线是错误色,节点上挂的也是 error 角标
 * (和后端运行前拦的那一条对上)。提示线不在图里 —— 画布上的删除、改动碰不到图。
 *
 * jsdom 里接点量不出位置,React Flow 画不出线;所以在它外面包一层,记下编辑器交给它的 props(和 BoardPendingLink
 * 那条测试同一个做法)。线在 DOM 上长什么样见 ReferenceHintEdge.dom.test。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import type { Edge, ReactFlowProps } from "@xyflow/react";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  listWorkflows: vi.fn(),
  fetchWorkflowNodeTypes: vi.fn(),
  updateWorkflow: vi.fn(),
  listWorkflowRuns: vi.fn(),
  runWorkflow: vi.fn(),
  listJobEvents: vi.fn(),
  listJobChildren: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), message: vi.fn(), info: vi.fn(), warning: vi.fn() }) }));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ...apiMocks,
}));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "me" } }) }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));

const flow: { props: ReactFlowProps | null } = { props: null };
vi.mock("@xyflow/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@xyflow/react")>();
  function RecordingFlow(props: ReactFlowProps) {
    flow.props = props;
    return <actual.ReactFlow {...props} />;
  }
  return { ...actual, ReactFlow: RecordingFlow };
});

import type { Workspace, WorkflowGraph } from "@/api/client";
import { canvasEdgeClass } from "@/components/app/canvasEdges";
import { TooltipProvider } from "@/components/ui/tooltip";
import { REFERENCE_HINT_EDGE_TYPE, isReferenceHintId } from "@/features/workflows/referenceHints";
import { WorkflowsView } from "@/features/workflows/WorkflowsView";
import { WithPageTrail } from "@/test/pageTrail";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("fetch", () => new Promise(() => undefined));
});

const NODE_TYPES = [
  { type: "start", label: "start", description: "", category: "", config: { params: { type: "object", editor: "map" } }, outputs: ["*params"], output_types: {}, output_labels: {} },
  { type: "llm", label: "llm", description: "", category: "", config: { prompt: { type: "template", required: true } }, outputs: ["text"], output_types: { text: "text" }, output_labels: {} },
  { type: "template", label: "template", description: "", category: "", config: { template: { type: "template", required: true } }, outputs: ["text"], output_types: { text: "text" }, output_labels: {} },
  { type: "loop_foreach", label: "loop", description: "", category: "", config: { items: { type: "template" }, body: { type: "graph" }, output: { type: "template" } }, outputs: ["results"], output_types: {}, output_labels: {}, body_scope: { loop: ["item", "index"], input: ["*inputs"] } },
];

function workflowWith(graph: WorkflowGraph) {
  return { id: "wf1", workspace_id: "w1", name: "测试", description: "", revision: 1, graph, created_at: "2026-09-20T00:00:00", updated_at: "2026-09-20T00:00:00" };
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("mosael:selected:workflows", "wf1");
  flow.props = null;
  apiMocks.fetchWorkflowNodeTypes.mockResolvedValue(NODE_TYPES);
  apiMocks.listWorkflowRuns.mockResolvedValue([]);
  apiMocks.listJobEvents.mockResolvedValue([]);
  apiMocks.listJobChildren.mockResolvedValue([]);
  apiMocks.updateWorkflow.mockImplementation(async (_id: string, body: { graph: WorkflowGraph }) => workflowWith(body.graph));
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function renderEditor(graph: WorkflowGraph) {
  apiMocks.listWorkflows.mockResolvedValue([workflowWith(graph)]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <WithPageTrail>
          <WorkflowsView workspace={{ id: "w1", name: "w" } as Workspace} />
        </WithPageTrail>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  await screen.findByRole("group", { name: "canvasTools" }, { timeout: 10000 });
}

function nodeEl(id: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(`.react-flow__node[data-id="${id}"]`);
  if (!el) throw new Error(`node ${id} not rendered`);
  return el;
}

/** 编辑器此刻交给 React Flow 的提示线(id → 边)。 */
function hints(): Map<string, Edge> {
  return new Map((flow.props?.edges ?? []).filter((edge) => isReferenceHintId(edge.id)).map((edge) => [edge.id, edge]));
}

const GRAPH = {
  nodes: [
    { id: "start", type: "start", position: { x: 0, y: 0 }, config: { params: { topic: "猫" } } },
    { id: "llm-1", type: "llm", position: { x: 200, y: 0 }, config: { prompt: "写分镜" } },
    //: 一条连线都没有,只靠下面那句引用挂着 —— 「可用的 3D 道具」的现场。
    { id: "props", type: "template", name: "道具", position: { x: 200, y: 200 }, config: { template: "桌子" } },
    { id: "set", type: "template", position: { x: 400, y: 0 }, config: { template: "{{llm-1.text}} {{start.topic}} {{props.text}}" } },
  ],
  edges: [
    { id: "e-start-llm-1", source: "start", target: "llm-1" },
    { id: "e-llm-1-set", source: "llm-1", target: "set" },
  ],
} as WorkflowGraph;

it("主流程:引用画成提示线(已有真连线的不画),从输出口出发;被引用的没接进流程时是错误色,节点上挂 error 角标", async () => {
  await renderEditor(GRAPH);
  await waitFor(() => expect(hints().size).toBe(2));
  expect([...hints().values()].map((edge) => [edge.source, edge.sourceHandle, edge.target, edge.className])).toEqual([
    ["start", undefined, "set", canvasEdgeClass("ref", { hint: true })],
    ["props", "out:text", "set", canvasEdgeClass("ref-never-runs", { hint: true })],
  ]);
  for (const edge of hints().values()) {
    expect(edge).toMatchObject({ type: REFERENCE_HINT_EDGE_TYPE, selectable: false, deletable: false, focusable: false, reconnectable: false });
  }
  //: 提示线排在真连线前面(先画,真连线压在上面);渲染器登记在 edgeTypes 里。
  const ids = (flow.props?.edges ?? []).map((edge) => edge.id);
  expect(ids.findIndex((id) => !isReferenceHintId(id))).toBe(hints().size);
  expect(flow.props?.edgeTypes?.[REFERENCE_HINT_EDGE_TYPE]).toBeDefined();
  //: 和就绪检查对上:被引用的那个挂的是 error(unwired-referenced),不是黄色提醒。
  expect(within(nodeEl("props")).getByLabelText("wfIssueUnwiredReferenced")).toBeTruthy();
});

it("连进流程之后:线变回淡色,角标消失;再接上真连线,那根提示线就不画了", async () => {
  await renderEditor({
    ...GRAPH,
    edges: [...GRAPH.edges, { id: "e-start-props", source: "start", target: "props" }],
  } as WorkflowGraph);
  await waitFor(() => expect(hints().size).toBe(2));
  expect(hints().get("ref-hint:props>out:text>set")?.className).toBe(canvasEdgeClass("ref", { hint: true }));
  expect(within(nodeEl("props")).queryByLabelText("wfIssueUnwiredReferenced")).toBeNull();
  //: 画布上连一根 props → set 的真连线。
  act(() => flow.props?.onConnect?.({ source: "props", target: "set", sourceHandle: null, targetHandle: null }));
  await waitFor(() => expect(hints().has("ref-hint:props>out:text>set")).toBe(false));
});

it("提示线不在图里:画布报来的删除落不到图上,也不触发保存", async () => {
  await renderEditor(GRAPH);
  await waitFor(() => expect(hints().size).toBe(2));
  act(() => flow.props?.onEdgesChange?.([{ type: "remove", id: "ref-hint:props>out:text>set" }]));
  await new Promise((resolve) => setTimeout(resolve, 1200));
  expect(apiMocks.updateWorkflow).not.toHaveBeenCalled();
  expect(hints().has("ref-hint:props>out:text>set")).toBe(true);
});

it("循环体里的引用照画;体里没有入边的根是入口,不算错误", async () => {
  await renderEditor({
    nodes: [
      { id: "start", type: "start", position: { x: 0, y: 0 }, config: { params: {} } },
      {
        id: "loop-1",
        type: "loop_foreach",
        position: { x: 200, y: 0 },
        config: {
          items: "a",
          output: "",
          body: {
            nodes: [
              { id: "style", type: "template", position: { x: 0, y: 0 }, config: { template: "胶片感" } },
              { id: "shot", type: "template", position: { x: 200, y: 0 }, config: { template: "{{loop.item}} {{style.text}}" } },
            ],
            edges: [],
          },
        },
      },
    ],
    edges: [{ id: "e-start-loop-1", source: "start", target: "loop-1" }],
  } as WorkflowGraph);
  await waitFor(() => nodeEl("loop-1"));
  expect(hints().size).toBe(0);
  fireEvent.click(nodeEl("loop-1"));
  fireEvent.doubleClick(nodeEl("loop-1"));
  await screen.findByText(/wfLoopBody/);
  await waitFor(() => expect([...hints().keys()]).toEqual(["ref-hint:style>out:text>shot"]));
  expect(hints().get("ref-hint:style>out:text>shot")?.className).toBe(canvasEdgeClass("ref", { hint: true }));
});
