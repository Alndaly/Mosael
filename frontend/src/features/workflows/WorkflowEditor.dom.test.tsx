/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  listWorkflows: vi.fn(),
  fetchWorkflowNodeTypes: vi.fn(),
  updateWorkflow: vi.fn(),
  listWorkflowRuns: vi.fn(),
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ...apiMocks,
}));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "me" } }) }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));

import type { Workspace, WorkflowGraph } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { WorkflowsView } from "@/features/workflows/WorkflowsView";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("fetch", () => new Promise(() => undefined));
});

const NODE_TYPES = [
  { type: "start", label: "start", description: "", category: "", config: { params: { type: "object", editor: "map" } }, outputs: ["*params"], output_types: {}, output_labels: {} },
  { type: "llm", label: "llm", description: "", category: "", config: { prompt: { type: "template", required: true } }, outputs: ["text"], output_types: { text: "text" }, output_labels: {} },
  { type: "template", label: "template", description: "", category: "", config: { template: { type: "template", required: true } }, outputs: ["text"], output_types: { text: "text" }, output_labels: {} },
  { type: "loop_foreach", label: "loop", description: "", category: "", config: { items: { type: "template" }, body: { type: "graph" }, output: { type: "template" } }, outputs: ["results"], output_types: {}, output_labels: {} },
];

function workflowWith(graph: WorkflowGraph) {
  return {
    id: "wf1",
    workspace_id: "w1",
    name: "测试",
    description: "",
    revision: 1,
    graph,
    created_at: "2026-09-20T00:00:00",
    updated_at: "2026-09-20T00:00:00",
  };
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("mosael:selected:workflows", "wf1");
  apiMocks.fetchWorkflowNodeTypes.mockResolvedValue(NODE_TYPES);
  apiMocks.listWorkflowRuns.mockResolvedValue([]);
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
        <WorkflowsView workspace={{ id: "w1", name: "w" } as Workspace} />
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

function nodeEl(id: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(`.react-flow__node[data-id="${id}"]`);
  if (!el) throw new Error(`node ${id} not rendered`);
  return el;
}

/** 点一个节点,再按住多选键点其余的。React Flow 的多选键在 macOS 是 ⌘、别处是 Ctrl ——
 *  jsdom 的 platform 是空串,走的是 Ctrl。 */
async function selectNodes(ids: string[]) {
  await waitFor(() => nodeEl(ids[0]));
  fireEvent.click(nodeEl(ids[0]));
  for (const id of ids.slice(1)) {
    fireEvent.keyDown(window, { key: "Control", ctrlKey: true });
    fireEvent.click(nodeEl(id), { ctrlKey: true });
    fireEvent.keyUp(window, { key: "Control" });
  }
  await waitFor(() => {
    for (const id of ids) expect(nodeEl(id).className).toContain("selected");
  });
}

const CHAIN: WorkflowGraph = {
  nodes: [
    { id: "start", type: "start", position: { x: 0, y: 0 }, config: {} },
    { id: "llm-1", type: "llm", position: { x: 200, y: 0 }, config: { prompt: "hi" } },
    { id: "template-1", type: "template", position: { x: 400, y: 0 }, config: { template: "前缀 {{llm-1.text}} / {{start.topic}}" } },
  ],
  edges: [
    { id: "e-start-llm-1", source: "start", target: "llm-1" },
    { id: "e-llm-1-template-1", source: "llm-1", target: "template-1" },
  ],
} as WorkflowGraph;

it("⌘/Ctrl 点击是往选区里加,不是换成只选这一个", async () => {
  await renderEditor(CHAIN);
  await selectNodes(["llm-1", "template-1"]);
  // 选了两个就不是在编辑某一个:检查器收起,换成「折叠为子图」。
  expect(screen.queryByLabelText("wfNodeName")).toBeNull();
  expect(screen.getByText("wfCollapseToSubgraph")).toBeTruthy();
});

it("复制粘贴一组节点:组内的 {{引用}} 跟着换成新节点,组外的不动", async () => {
  await renderEditor(CHAIN);
  await selectNodes(["llm-1", "template-1"]);
  fireEvent.keyDown(window, { key: "c", metaKey: true });
  fireEvent.keyDown(window, { key: "v", metaKey: true });
  const graph = await savedGraph();
  const pasted = graph.nodes.find((node) => node.id === "template-2");
  expect(pasted?.config).toEqual({ template: "前缀 {{llm-2.text}} / {{start.topic}}" });
  // 原件原样不动。
  expect(graph.nodes.find((node) => node.id === "template-1")?.config).toEqual(CHAIN.nodes[2].config);
});

const LOOPED: WorkflowGraph = {
  nodes: [
    { id: "start", type: "start", position: { x: 0, y: 0 }, config: {} },
    {
      id: "loop-1",
      type: "loop_foreach",
      position: { x: 200, y: 0 },
      config: {
        items: "{{start.list}}",
        output: "",
        body: {
          nodes: [{ id: "template-1", type: "template", name: "体内", position: { x: 0, y: 0 }, config: { template: "{{loop.item}}" } }],
          edges: [],
        },
      },
    },
  ],
  edges: [{ id: "e-start-loop-1", source: "start", target: "loop-1" }],
} as WorkflowGraph;

/** 双击循环节点钻进循环体 —— 和用户的路径一致(双击之前那一下单击会选中循环节点)。 */
async function drillInto(id: string) {
  await waitFor(() => nodeEl(id));
  fireEvent.click(nodeEl(id));
  fireEvent.doubleClick(nodeEl(id));
  await screen.findByText(/wfLoopBody/);
}

it("循环体里按 Delete 删的是循环体里选中的节点,不会把外面那个循环节点一起删掉", async () => {
  await renderEditor(LOOPED);
  await drillInto("loop-1");
  await waitFor(() => nodeEl("template-1"));
  fireEvent.click(nodeEl("template-1"));
  fireEvent.keyDown(document.body, { key: "Backspace" });
  fireEvent.keyUp(document.body, { key: "Backspace" });
  const graph = await savedGraph();
  expect(graph.nodes.map((node) => node.id)).toEqual(["start", "loop-1"]);
  expect(graph.nodes[1].config).toMatchObject({ body: { nodes: [] } });
});

it("循环体里的改动能撤销,撤销后循环体画面跟着变回去", async () => {
  await renderEditor(LOOPED);
  await drillInto("loop-1");
  await waitFor(() => nodeEl("template-1"));
  fireEvent.click(nodeEl("template-1"));
  const name = await screen.findByLabelText("wfNodeName");
  fireEvent.change(name, { target: { value: "体内a" } });
  fireEvent.change(name, { target: { value: "体内ab" } });
  await waitFor(() => expect(nodeEl("template-1").textContent).toContain("体内ab"));
  // 一串输入在历史里是一条:撤一次就回到输入之前。
  fireEvent.click(screen.getAllByRole("button", { name: "undo" }).at(-1)!);
  await waitFor(() => expect(nodeEl("template-1").textContent).not.toContain("体内a"));
  expect((screen.getByLabelText("wfNodeName") as HTMLInputElement).value).toBe("体内");
});

it("循环体里 ⌘C ⌘V 复制的是循环体里的节点,粘进循环体", async () => {
  await renderEditor(LOOPED);
  await drillInto("loop-1");
  await waitFor(() => nodeEl("template-1"));
  fireEvent.click(nodeEl("template-1"));
  fireEvent.keyDown(document.body, { key: "c", metaKey: true });
  fireEvent.keyDown(document.body, { key: "v", metaKey: true });
  const graph = await savedGraph();
  // 外层图没有多出节点;粘出来的那一个在循环体里。
  expect(graph.nodes.map((node) => node.id)).toEqual(["start", "loop-1"]);
  const body = graph.nodes[1].config!.body as WorkflowGraph;
  expect(body.nodes.map((node) => node.id)).toEqual(["template-1", "template-2"]);
});

it("循环体里套的循环也能钻进去,改动写进最里面那层,返回一次回上一层", async () => {
  const inner = { nodes: [{ id: "template-1", type: "template", name: "最里", position: { x: 0, y: 0 }, config: { template: "" } }], edges: [] };
  const graph = structuredClone(LOOPED);
  (graph.nodes[1].config!.body as WorkflowGraph).nodes.push({
    id: "loop-2", type: "loop_foreach", name: "内层", position: { x: 300, y: 0 }, config: { items: "", body: inner },
  } as WorkflowGraph["nodes"][number]);
  await renderEditor(graph);
  await drillInto("loop-1");
  await waitFor(() => nodeEl("loop-2"));
  fireEvent.click(nodeEl("loop-2"));
  fireEvent.doubleClick(nodeEl("loop-2"));
  await screen.findByText("内层 · wfLoopBody");
  fireEvent.click(nodeEl("template-1"));
  fireEvent.change(await screen.findByLabelText("wfNodeName"), { target: { value: "改过" } });
  const saved = await savedGraph();
  const outerBody = saved.nodes[1].config!.body as WorkflowGraph;
  const innerBody = outerBody.nodes.find((node) => node.id === "loop-2")!.config!.body as WorkflowGraph;
  expect(innerBody.nodes[0].name).toBe("改过");
  // 外层体里同名的 template-1 不受影响。
  expect(outerBody.nodes.find((node) => node.id === "template-1")?.name).toBe("体内");
  fireEvent.click(screen.getByRole("button", { name: "wfLoopBack" }));
  await screen.findByText("loop · wfLoopBody");
});
