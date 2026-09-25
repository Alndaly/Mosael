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
