/** @vitest-environment jsdom */
/**
 * 工作流自动保存的乐观并发:每次保存都带着底子(读到的那份图的 graph_hash),撞了 409 就载入
 * 服务端那份,而不是拿画布上的旧底子把智能体 / 另一个窗口刚写的图盖掉。和画板同一套规矩
 * (见 lib/optimisticWrites)。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  listWorkflows: vi.fn(),
  getWorkflow: vi.fn(),
  fetchWorkflowNodeTypes: vi.fn(),
  updateWorkflow: vi.fn(),
  listWorkflowRuns: vi.fn(),
  runWorkflow: vi.fn(),
}));
const toastMocks = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), message: vi.fn() }));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ...apiMocks,
}));
vi.mock("sonner", async (importOriginal) => ({
  ...(await importOriginal<typeof import("sonner")>()),
  toast: toastMocks,
}));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "me" } }) }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));

import { ApiError, type Workspace, type WorkflowGraph } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { WorkflowsView } from "@/features/workflows/WorkflowsView";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("fetch", () => new Promise(() => undefined));
});

const NODE_TYPES = [
  { type: "start", label: "start", description: "", category: "", config: { params: { type: "object", editor: "map" } }, outputs: ["*params"], output_types: {}, output_labels: {} },
  { type: "llm", label: "llm", description: "", category: "", config: { prompt: { type: "template", required: true } }, outputs: ["text"], output_types: { text: "text" }, output_labels: {} },
];

const GRAPH: WorkflowGraph = {
  nodes: [
    { id: "start", type: "start", position: { x: 0, y: 0 }, config: {} },
    { id: "llm-1", type: "llm", name: "原名", position: { x: 200, y: 0 }, config: { prompt: "hi" } },
  ],
  edges: [{ id: "e-start-llm-1", source: "start", target: "llm-1" }],
} as WorkflowGraph;

function workflowWith(graph: WorkflowGraph, hash: string, updatedAt = "2026-09-20T00:00:00") {
  return {
    id: "wf1",
    workspace_id: "w1",
    name: "测试",
    description: "",
    revision: 1,
    graph_hash: hash,
    graph,
    created_at: "2026-09-20T00:00:00",
    updated_at: updatedAt,
  };
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("mosael:selected:workflows", "wf1");
  apiMocks.fetchWorkflowNodeTypes.mockResolvedValue(NODE_TYPES);
  apiMocks.listWorkflowRuns.mockResolvedValue([]);
  apiMocks.listWorkflows.mockResolvedValue([workflowWith(GRAPH, "h0")]);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function renderEditor() {
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

async function renameLlm(value: string) {
  await waitFor(() => nodeEl("llm-1"));
  fireEvent.click(nodeEl("llm-1"));
  fireEvent.change(await screen.findByLabelText("wfNodeName"), { target: { value } });
}

type SaveBody = { graph: WorkflowGraph; base_graph_hash: string };
const bodies = () => apiMocks.updateWorkflow.mock.calls.map((call) => call[1] as SaveBody);

it("每次保存都带着底子;下一次用的是上一次存回来的那份", async () => {
  let n = 0;
  apiMocks.updateWorkflow.mockImplementation(async (_id: string, body: SaveBody) => workflowWith(body.graph, `h${++n}`));
  await renderEditor();
  await renameLlm("改一");
  await waitFor(() => expect(bodies()).toHaveLength(1), { timeout: 3000 });
  expect(bodies()[0].base_graph_hash).toBe("h0");
  fireEvent.change(screen.getByLabelText("wfNodeName"), { target: { value: "改二" } });
  await waitFor(() => expect(bodies()).toHaveLength(2), { timeout: 3000 });
  expect(bodies()[1].base_graph_hash).toBe("h1");
});

it("保存途中又改了一处:那一处在这次保存回来之后照样存上,并且带着新底子", async () => {
  let release: (() => void) | null = null;
  let n = 0;
  apiMocks.updateWorkflow.mockImplementation(async (_id: string, body: SaveBody) => {
    n += 1;
    if (n === 1) await new Promise<void>((resolve) => (release = resolve));
    return workflowWith(body.graph, `h${n}`);
  });
  await renderEditor();
  await renameLlm("改一");
  await waitFor(() => expect(release).not.toBeNull(), { timeout: 3000 });
  fireEvent.change(screen.getByLabelText("wfNodeName"), { target: { value: "改二" } });
  // 让第二次编辑的去抖先到点,再放第一次保存回来。
  await new Promise((resolve) => setTimeout(resolve, 800));
  release!();
  await waitFor(() => expect(bodies()).toHaveLength(2), { timeout: 3000 });
  expect(bodies()[1].graph.nodes[1].name).toBe("改二");
  expect(bodies()[1].base_graph_hash).toBe("h1");
});

it("撞 409:载入服务端那份、撤销历史清空、告诉用户,而不是盖掉别人的改动", async () => {
  const theirs = structuredClone(GRAPH);
  theirs.nodes[1].name = "别处改的";
  const server = workflowWith(theirs, "h9", "2026-09-20T00:00:09");
  apiMocks.updateWorkflow.mockImplementation(async () => {
    // 服务端早已是别人写的那一份 —— 列表轮询此后拿到的也是它。
    apiMocks.listWorkflows.mockResolvedValue([server]);
    throw new ApiError("conflict", 409, "{}");
  });
  apiMocks.getWorkflow.mockResolvedValue(server);
  await renderEditor();
  await renameLlm("我改的");
  await waitFor(() => expect(nodeEl("llm-1").textContent).toContain("别处改的"), { timeout: 3000 });
  expect(apiMocks.getWorkflow).toHaveBeenCalledWith("wf1");
  expect(toastMocks.error).toHaveBeenCalledWith("wfSaveConflict", { description: "wfSaveConflictDetail" });
  // 撤销历史对着的是被丢掉的那份本地图,留着的话一按撤销就把旧图又写回去。
  const undo = screen.getAllByRole("button", { name: "undo" }).at(-1) as HTMLButtonElement;
  expect(undo.disabled).toBe(true);
  // 冲突不是「保存失败」:不再弹第二句。
  expect(toastMocks.error).not.toHaveBeenCalledWith("wfSaveFailed", expect.anything());

  // 之后的编辑以服务端那份为底子。
  apiMocks.updateWorkflow.mockImplementation(async (_id: string, body: SaveBody) => workflowWith(body.graph, "h10"));
  await renameLlm("再改");
  await waitFor(() => expect(bodies().at(-1)?.graph.nodes[1].name).toBe("再改"), { timeout: 3000 });
  expect(bodies().at(-1)?.base_graph_hash).toBe("h9");
});
