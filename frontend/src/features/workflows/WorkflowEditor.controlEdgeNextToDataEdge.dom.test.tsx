/** @vitest-environment jsdom */
/**
 * 同一对节点上「数据边 + 控制边」同时在:自动保存发出去的图两条边都在,服务端把这一版回传
 * (props 同步那条路)之后,画布不能被旧 props 盖掉 —— 控制边得还在。
 *
 * 丢边的真凶不在这边:后端规范化(normalization.canonicalize_data_bindings)曾把「同一对节点间
 * 有数据边」的无 handle 控制边当多余的折掉,库里的图因此少了控制边,下一次刷新它就没回来。
 * 那一路由 backend/tests/test_control_edge_next_to_data_edge_survives_save.py 钉住(红 → 绿)。
 * 这个文件钉前端这一半的合同:编辑器发的图两条边都在(useWorkflowSave 原样发 graphStore 的图),
 * 以及保存回传 / 轮询同步(useWorkflowSave 的 serverSync + selfSaveRef)不把画布上的控制边盖掉。
 *
 * jsdom 里接点量不出位置,React Flow 画不出线;所以在它外面包一层,记下编辑器交给它的 props,
 * 直接调 onConnect(和 WorkflowEditor.referenceHints.dom.test 同一个做法)。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import type { ReactFlowProps } from "@xyflow/react";
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
import { isReferenceHintId } from "@/features/workflows/referenceHints";
import { TooltipProvider } from "@/components/ui/tooltip";
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
];

function workflowWith(graph: WorkflowGraph, updatedAt = "2026-09-20T00:00:00", graphHash = "h-1") {
  return { id: "wf1", workspace_id: "w1", name: "测试", description: "", revision: 1, graph, graph_hash: graphHash, created_at: "2026-09-20T00:00:00", updated_at: updatedAt };
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("mosael:selected:workflows", "wf1");
  flow.props = null;
  apiMocks.fetchWorkflowNodeTypes.mockResolvedValue(NODE_TYPES);
  apiMocks.listWorkflowRuns.mockResolvedValue([]);
  apiMocks.listJobEvents.mockResolvedValue([]);
  apiMocks.listJobChildren.mockResolvedValue([]);
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

/** 最后一次保存出去的图 —— 编辑器的"落库结果"。 */
async function savedGraph(): Promise<WorkflowGraph> {
  await waitFor(() => expect(apiMocks.updateWorkflow).toHaveBeenCalled(), { timeout: 3000 });
  const calls = apiMocks.updateWorkflow.mock.calls;
  return (calls[calls.length - 1][1] as { graph: WorkflowGraph }).graph;
}

/** 画布上现在画着的真连线(id → 边;提示线不算)。 */
function canvasEdges(): Map<string, { source: string; target: string }> {
  return new Map(
    (flow.props?.edges ?? [])
      .filter((edge) => !isReferenceHintId(edge.id))
      .map((edge) => [edge.id, { source: edge.source, target: edge.target }]),
  );
}

const GRAPH = {
  nodes: [
    { id: "start", type: "start", position: { x: 0, y: 0 }, config: { params: {} } },
    { id: "llm-1", type: "llm", position: { x: 200, y: 0 }, config: { prompt: "写" } },
    { id: "template-1", type: "template", position: { x: 400, y: 0 }, config: { template: "" } },
  ],
  edges: [{ id: "e-start-llm-1", source: "start", target: "llm-1" }],
} as WorkflowGraph;

it("同一对节点上数据边 + 控制边:自动保存把两条边都发出去;服务端回传这一版后画布不被旧 props 盖掉", async () => {
  await renderEditor(GRAPH);
  // 和维护者的复现路径一致:先连数据边(out:text → in:template),再连控制边(▶ 口 → 节点)。
  act(() => flow.props?.onConnect?.({ source: "llm-1", target: "template-1", sourceHandle: "out:text", targetHandle: "in:template" }));
  act(() => flow.props?.onConnect?.({ source: "llm-1", target: "template-1", sourceHandle: null, targetHandle: null }));
  // 此刻画布上两条边都在。
  expect(canvasEdges().has("d-llm-1-text-template-1-template")).toBe(true);
  expect(canvasEdges().has("e-llm-1-template-1")).toBe(true);

  // 服务端确认这次保存:推进 updated_at / graph_hash(像真后端那样),listWorkflows 随后回这一版。
  apiMocks.updateWorkflow.mockImplementation(async (_id: string, body: { graph: WorkflowGraph }) =>
    workflowWith(body.graph, "2026-09-20T00:01:00", "h-2"),
  );
  let served = workflowWith(GRAPH, "2026-09-20T00:00:00", "h-1");
  apiMocks.listWorkflows.mockImplementation(async () => [served]);

  // 自动保存(700ms 防抖)发出去的图:数据边和控制边都在 —— 丢哪条都不是编辑器该发的。
  const sent = await savedGraph();
  expect(sent.edges.map((edge) => edge.id)).toEqual(
    expect.arrayContaining(["d-llm-1-text-template-1-template", "e-llm-1-template-1"]),
  );
  // 保存回传invalidate 触发重拉:props 换成「自己刚存的这一版」。同步 effect 该认下它
  // (selfSaveRef),**不重建画布** —— 两条边都得还在画布上。
  served = workflowWith(sent, "2026-09-20T00:01:00", "h-2");
  await waitFor(() => expect(canvasEdges().has("e-llm-1-template-1")).toBe(true));
  expect(canvasEdges().has("d-llm-1-text-template-1-template")).toBe(true);
}, 20000);

it("两条边是一次离散操作各记一条:撤一次只退控制边,再撤一次退数据边", async () => {
  await renderEditor(GRAPH);
  act(() => flow.props?.onConnect?.({ source: "llm-1", target: "template-1", sourceHandle: "out:text", targetHandle: "in:template" }));
  act(() => flow.props?.onConnect?.({ source: "llm-1", target: "template-1", sourceHandle: null, targetHandle: null }));
  await waitFor(() => expect(canvasEdges().has("e-llm-1-template-1")).toBe(true));

  act(() => screen.getAllByRole("button", { name: "undo" }).at(-1)!.click());
  await waitFor(() => expect(canvasEdges().has("e-llm-1-template-1")).toBe(false));
  expect(canvasEdges().has("d-llm-1-text-template-1-template")).toBe(true);

  act(() => screen.getAllByRole("button", { name: "undo" }).at(-1)!.click());
  await waitFor(() => expect(canvasEdges().has("d-llm-1-text-template-1-template")).toBe(false));
}, 20000);
