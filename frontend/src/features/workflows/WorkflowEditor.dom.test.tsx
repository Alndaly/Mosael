/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  listWorkflows: vi.fn(),
  fetchWorkflowNodeTypes: vi.fn(),
  updateWorkflow: vi.fn(),
  listWorkflowRuns: vi.fn(),
  runWorkflow: vi.fn(),
  listJobEvents: vi.fn(),
  listJobChildren: vi.fn(),
}));
const toastMocks = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), message: vi.fn(), info: vi.fn(), warning: vi.fn() }));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), toastMocks) }));

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
import { readHint } from "@/test/hint";
import { WithPageTrail } from "@/test/pageTrail";
import { TooltipProvider } from "@/components/ui/tooltip";
import { WorkflowsView } from "@/features/workflows/WorkflowsView";
import { installSaveShortcut } from "@/lib/saveShortcut";

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
  apiMocks.listJobEvents.mockResolvedValue([]);
  apiMocks.listJobChildren.mockResolvedValue([]);
  apiMocks.runWorkflow.mockResolvedValue({ id: "job-1", status: "queued" });
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
    { id: "start", type: "start", position: { x: 0, y: 0 }, config: { params: { topic: "" } } },
    { id: "llm-1", type: "llm", position: { x: 200, y: 0 }, config: { prompt: "hi" } },
    { id: "template-1", type: "template", position: { x: 400, y: 0 }, config: { template: "前缀 {{llm-1.text}} / {{start.topic}}" } },
  ],
  edges: [
    { id: "e-start-llm-1", source: "start", target: "llm-1" },
    { id: "e-llm-1-template-1", source: "llm-1", target: "template-1" },
  ],
} as WorkflowGraph;

it("顶栏路径:最外层时最后一段是工作流的名字,点它改名;点页面名回到清单", async () => {
  await renderEditor(CHAIN);
  const trail = screen.getByRole("navigation", { name: "page-trail" });
  fireEvent.click(within(trail).getByRole("button", { name: "测试" }));
  expect(await screen.findByRole("dialog")).toBeTruthy();
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  fireEvent.click(within(trail).getByRole("button", { name: "trail-root" }));
  await waitFor(() => expect(screen.queryByRole("group", { name: "canvasTools" })).toBeNull());
});

it("⌘/Ctrl 点击是往选区里加,不是换成只选这一个", async () => {
  await renderEditor(CHAIN);
  await selectNodes(["llm-1", "template-1"]);
  // 选了两个就不是在编辑某一个:检查器收起,换成「折叠为子图」。
  expect(screen.queryByLabelText("wfNodeName")).toBeNull();
  expect(screen.getByText("wfCollapseToSubgraph")).toBeTruthy();
});

it("Shift 点击也是往选区里加(和画板、时间线、3D 关键帧同一条规则)", async () => {
  await renderEditor(CHAIN);
  await waitFor(() => nodeEl("llm-1"));
  fireEvent.click(nodeEl("llm-1"));
  fireEvent.keyDown(window, { key: "Shift", shiftKey: true });
  fireEvent.click(nodeEl("template-1"), { shiftKey: true });
  fireEvent.keyUp(window, { key: "Shift" });
  await waitFor(() => {
    expect(nodeEl("llm-1").className).toContain("selected");
    expect(nodeEl("template-1").className).toContain("selected");
  });
});

it("双击画布空白处不缩放(两块画布同一份指针设置;缩放走捏合、滚轮和工具条)", async () => {
  await renderEditor(CHAIN);
  await waitFor(() => nodeEl("llm-1"));
  //: React Flow 缺省的双击缩放挂在 d3-zoom 上,处理双击时 stopImmediatePropagation —— 看事件有没有被它吞掉。
  //: (不比视口前后:挂上时那次适配在下一帧,机器忙的时候晚到,前后一比就成了偶发的红。)
  const reached = vi.fn();
  document.addEventListener("dblclick", reached);
  try {
    fireEvent.doubleClick(document.querySelector<HTMLElement>(".react-flow__pane")!, { clientX: 300, clientY: 200 });
  } finally {
    document.removeEventListener("dblclick", reached);
  }
  expect(reached).toHaveBeenCalledTimes(1);
});

it("⌘S 在检查器的字段里也存(不等自动保存那 700ms),也不让浏览器弹「存储网页」", async () => {
  //: main.tsx 装的那一个全局监听(lib/saveShortcut);此前这里的 ⌘S 只在画布焦点时接,字段里让路。
  const uninstall = installSaveShortcut(window);
  try {
    await renderEditor(CHAIN);
    await waitFor(() => nodeEl("llm-1"));
    fireEvent.click(nodeEl("llm-1"));
    const name = await screen.findByLabelText("wfNodeName");
    fireEvent.change(name, { target: { value: "改过的名字" } });
    const event = new KeyboardEvent("keydown", { key: "s", code: "KeyS", metaKey: true, bubbles: true, cancelable: true });
    act(() => void name.dispatchEvent(event));
    expect(event.defaultPrevented).toBe(true);
    await waitFor(() => expect(apiMocks.updateWorkflow).toHaveBeenCalled(), { timeout: 400 });
    const graph = (apiMocks.updateWorkflow.mock.calls[0][1] as { graph: WorkflowGraph }).graph;
    expect(graph.nodes.find((node) => node.id === "llm-1")?.name).toBe("改过的名字");
  } finally {
    uninstall();
  }
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
    { id: "start", type: "start", position: { x: 0, y: 0 }, config: { params: { list: "[]" } } },
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
  //: 顶栏的路径:工作流 / 名字 / loop · 循环体 / 内层 · 循环体 —— 点中间那一层回上一层。
  const trail = screen.getByRole("navigation", { name: "page-trail" });
  fireEvent.click(within(trail).getByRole("button", { name: "loop · wfLoopBody" }));
  await waitFor(() => expect(within(trail).queryByText("内层 · wfLoopBody")).toBeNull());
  expect(within(trail).getByText("loop · wfLoopBody").getAttribute("aria-current")).toBe("page");
});

it("焦点在检查器里(按钮、下拉)时按 Backspace 不删节点", async () => {
  await renderEditor(CHAIN);
  await waitFor(() => nodeEl("llm-1"));
  fireEvent.click(nodeEl("llm-1"));
  const panel = await screen.findByRole("complementary", { name: "llm" });
  // 点过「手动 / 连接」切换之后焦点就停在这颗按钮上 —— 下一下 Backspace 是冲着面板去的。
  const toggle = within(panel).getByRole("button", { name: /wfInputManual/ });
  toggle.focus();
  fireEvent.keyDown(toggle, { key: "Backspace" });
  fireEvent.keyUp(toggle, { key: "Backspace" });
  // 再改一下名字,逼出一次保存,看存下去的图。
  fireEvent.change(within(panel).getByLabelText("wfNodeName"), { target: { value: "改名" } });
  const graph = await savedGraph();
  expect(graph.nodes.map((node) => node.id)).toContain("llm-1");
});

it("检查器里展开的下拉(Portal 到 body)里按 Backspace 不删节点", async () => {
  Object.assign(Element.prototype, { hasPointerCapture: () => false, setPointerCapture: () => {}, releasePointerCapture: () => {}, scrollIntoView: () => {} });
  await renderEditor(CHAIN);
  await waitFor(() => nodeEl("llm-1"));
  fireEvent.click(nodeEl("llm-1"));
  const panel = await screen.findByRole("complementary", { name: "llm" });
  const trigger = within(panel).getAllByRole("combobox")[0];
  fireEvent.pointerDown(trigger, { button: 0, pointerType: "mouse" });
  fireEvent.click(trigger);
  const option = await screen.findByRole("option", { name: /wfPresetPrecise/ });
  option.focus();
  fireEvent.keyDown(option, { key: "Backspace" });
  fireEvent.keyUp(option, { key: "Backspace" });
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(document.querySelector('.react-flow__node[data-id="llm-1"]')).not.toBeNull();
  expect(apiMocks.updateWorkflow).not.toHaveBeenCalled();
});

it("画布上选中节点按 Backspace 照常删", async () => {
  await renderEditor(CHAIN);
  await waitFor(() => nodeEl("template-1"));
  fireEvent.click(nodeEl("template-1"));
  fireEvent.keyDown(nodeEl("template-1"), { key: "Backspace" });
  const graph = await savedGraph();
  expect(graph.nodes.map((node) => node.id)).toEqual(["start", "llm-1"]);
  expect(graph.edges.map((edge) => edge.id)).toEqual(["e-start-llm-1"]);
});

it("在检查器里展开的下拉上按 Esc 只收起下拉,检查器还开着", async () => {
  Object.assign(Element.prototype, { hasPointerCapture: () => false, setPointerCapture: () => {}, releasePointerCapture: () => {}, scrollIntoView: () => {} });
  await renderEditor(CHAIN);
  await waitFor(() => nodeEl("llm-1"));
  fireEvent.click(nodeEl("llm-1"));
  const panel = await screen.findByRole("complementary", { name: "llm" });
  const trigger = within(panel).getAllByRole("combobox")[0];
  fireEvent.pointerDown(trigger, { button: 0, pointerType: "mouse" });
  fireEvent.click(trigger);
  const option = await screen.findByRole("option", { name: /wfPresetPrecise/ });
  option.focus();
  fireEvent.keyDown(option, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("option", { name: /wfPresetPrecise/ })).toBeNull());
  expect(screen.getByLabelText("wfNodeName")).toBeTruthy();
  // 画布上的 Esc 照常收起检查器。
  fireEvent.keyDown(document.body, { key: "Escape" });
  await waitFor(() => expect(screen.queryByLabelText("wfNodeName")).toBeNull());
});

it("刚改完名字就换了下拉:是两步,撤一次只退回下拉", async () => {
  //: 打字才合并成一条历史;换下拉是离散的一步。此前检查器把**所有**配置改动都当成打字,
  //: 400ms 内的这两下被并成一条,撤一次名字和下拉一起退回去。
  Object.assign(Element.prototype, { hasPointerCapture: () => false, setPointerCapture: () => {}, releasePointerCapture: () => {}, scrollIntoView: () => {} });
  await renderEditor(CHAIN);
  await waitFor(() => nodeEl("llm-1"));
  fireEvent.click(nodeEl("llm-1"));
  const panel = await screen.findByRole("complementary", { name: "llm" });
  fireEvent.change(within(panel).getByLabelText("wfNodeName"), { target: { value: "改过的名字" } });
  const trigger = within(panel).getAllByRole("combobox")[0];
  fireEvent.pointerDown(trigger, { button: 0, pointerType: "mouse" });
  fireEvent.click(trigger);
  fireEvent.click(await screen.findByRole("option", { name: /wfPresetPrecise/ }));
  await waitFor(() => expect(nodeEl("llm-1").textContent).toContain("改过的名字"));
  fireEvent.click(screen.getAllByRole("button", { name: "undo" }).at(-1)!);
  await waitFor(async () => {
    const graph = await savedGraph();
    expect(graph.nodes[1].config?.preset).toBeUndefined();
    expect(graph.nodes[1].name).toBe("改过的名字");
  }, { timeout: 3000 });
});

describe("⌘Enter 运行", () => {
  //: 运行跑的是**服务端存着的那一版**。工具栏的运行键在「还没存完」和「有阻断问题」时是灰的,
  //: 快捷键此前绕过了这两条:改完立刻按 ⌘Enter,跑的是改之前的图。
  it("还有没存的改动时,先存再跑 —— 跑的是屏幕上这一版", async () => {
    const order: string[] = [];
    apiMocks.updateWorkflow.mockImplementation(async (_id: string, body: { graph: WorkflowGraph }) => {
      order.push("save");
      return workflowWith(body.graph);
    });
    apiMocks.runWorkflow.mockImplementation(async () => {
      order.push("run");
      return { id: "job-1", status: "queued" };
    });
    await renderEditor(CHAIN);
    await waitFor(() => nodeEl("llm-1"));
    fireEvent.click(nodeEl("llm-1"));
    fireEvent.change(await screen.findByLabelText("wfNodeName"), { target: { value: "改过" } });
    fireEvent.keyDown(document.body, { key: "Enter", metaKey: true });
    await waitFor(() => expect(order).toContain("run"));
    expect(order).toEqual(["save", "run"]);
  });

  //: 自动保存撞上非 409 的错误后 dirty 一直是 true。运行键此前按 dirty 灰着、说「保存中…」,
  //: 永远点不动;现在和 ⌘Enter 同一个判据:点了先重存再跑。
  it("自动保存失败后运行键不灰、不说「保存中」;点它先重存再跑", async () => {
    const order: string[] = [];
    apiMocks.updateWorkflow.mockImplementationOnce(async () => {
      order.push("save-failed");
      throw new Error("boom");
    });
    apiMocks.updateWorkflow.mockImplementation(async (_id: string, body: { graph: WorkflowGraph }) => {
      order.push("save");
      return workflowWith(body.graph);
    });
    apiMocks.runWorkflow.mockImplementation(async () => {
      order.push("run");
      return { id: "job-1", status: "queued" };
    });
    await renderEditor(CHAIN);
    await waitFor(() => nodeEl("llm-1"));
    fireEvent.click(nodeEl("llm-1"));
    fireEvent.change(await screen.findByLabelText("wfNodeName"), { target: { value: "改过" } });
    await waitFor(() => expect(order).toEqual(["save-failed"]), { timeout: 3000 });
    const runButton = screen.getByRole("button", { name: "wfRun" });
    // 说明是「名字 + 补充」:补充那句是「点了先重存」,不是「保存中…」。
    await waitFor(async () => expect(await readHint(runButton)).toBe("wfRunwfRunRetriesSave"));
    expect(runButton).not.toHaveProperty("disabled", true);
    fireEvent.click(runButton);
    await waitFor(() => expect(order).toContain("run"));
    expect(order).toEqual(["save-failed", "save", "run"]);
  });

  //: 重入闸此前是 state:同一帧连按两次,两次闭包读到的都是「没在启动」,排了两次运行。
  it("同一帧连按两次 ⌘Enter 只排一次运行", async () => {
    await renderEditor(CHAIN);
    await waitFor(() => nodeEl("llm-1"));
    // 两下放进同一个 act:中间不重渲染,和真机上同一帧里的两次按键一样,两次都跑同一个闭包。
    act(() => {
      fireEvent.keyDown(document.body, { key: "Enter", metaKey: true });
      fireEvent.keyDown(document.body, { key: "Enter", metaKey: true });
    });
    await waitFor(() => expect(apiMocks.runWorkflow).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(apiMocks.runWorkflow).toHaveBeenCalledTimes(1);
  });

  //: 运行中工具栏上的运行键换成了停止键,⌘Enter 此前却不看这个:再按一下就再排一次付费运行。
  it("正在运行时按 ⌘Enter 不再起一次,提示正在运行", async () => {
    apiMocks.listWorkflowRuns.mockResolvedValue([
      { id: "job-0", kind: "workflow", status: "running", message: "", created_at: "2026-09-20T02:00:00", updated_at: "2026-09-20T02:00:01", payload: {} },
    ]);
    await renderEditor(CHAIN);
    await waitFor(() => nodeEl("llm-1"));
    await screen.findByRole("button", { name: "wfStop" }, SLOW);
    fireEvent.keyDown(document.body, { key: "Enter", metaKey: true });
    await waitFor(() => expect(toastMocks.info).toHaveBeenCalledWith("wfRunAlreadyRunning"));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(apiMocks.runWorkflow).not.toHaveBeenCalled();
  });

  //: 不跑,但也不能什么都不发生:运行键这时是灰的,按 ⌘Enter 的人不知道是没按到还是有问题。
  it("有阻断问题时不跑(和运行键同一个判据),而是打开就绪清单说哪儿有问题", async () => {
    const broken = structuredClone(CHAIN);
    broken.nodes[2].config = { template: "" };
    await renderEditor(broken);
    await waitFor(() => nodeEl("llm-1"));
    expect(screen.queryByText("wfChecklistBlocked")).toBeNull();
    fireEvent.keyDown(document.body, { key: "Enter", metaKey: true });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(apiMocks.runWorkflow).not.toHaveBeenCalled();
    const checklist = await screen.findByRole("menu", { name: "wfChecklist" });
    expect(within(checklist).getByText("wfChecklistBlocked")).toBeTruthy();
    expect(within(checklist).getByText("template")).toBeTruthy();
  });
});

it("钻进一层时,新画布定位好之前是藏着的(不在默认视口上闪一帧)", async () => {
  await renderEditor(LOOPED);
  await waitFor(() => nodeEl("loop-1"));
  await waitFor(() => expect(document.querySelector(".react-flow")!.className).not.toContain("opacity-0"));
  fireEvent.click(nodeEl("loop-1"));
  fireEvent.doubleClick(nodeEl("loop-1"));
  expect(document.querySelector(".react-flow")!.className).toContain("opacity-0");
  await waitFor(() => expect(document.querySelector(".react-flow")!.className).not.toContain("opacity-0"));
});

//: 整套一起跑时机器忙,画布挂载 + 钻层 + 定位要比默认的 1 秒久(renderEditor 等画布也给了 10 秒)。
const SLOW = { timeout: 10000 };
const SLOW_TEST = 30000;

describe("正在看哪一次运行 —— 画布、检查器、执行历史只有一个答案", () => {
  const RUNS = [
    { id: "new", kind: "workflow", status: "succeeded", message: "最新一次", created_at: "2026-09-20T02:00:00", updated_at: "2026-09-20T02:00:05", payload: {} },
    { id: "old", kind: "workflow", status: "failed", message: "较早一次", created_at: "2026-09-20T01:00:00", updated_at: "2026-09-20T01:00:05", payload: {} },
  ];
  const events = (jobId: string) => {
    const at = "2026-09-20T01:00:01Z";
    const step =
      jobId === "new"
        ? { id: "e1", job_id: jobId, type: "workflow.node.finished", created_at: at, payload: { node_id: "llm-1", name: "llm", outputs: {} } }
        : { id: "e1", job_id: jobId, type: "workflow.node.failed", created_at: at, payload: { node_id: "llm-1", name: "llm", error: "挂了" } };
    return [step, { id: "e2", job_id: jobId, type: "workflow.finished", created_at: at, payload: {} }];
  };
  const llmShows = (tone: "success" | "destructive") => nodeEl("llm-1").querySelector(`.text-${tone}`) !== null;

  it("在历史里点开一次旧的,画布跟着换;「回到最新」一下三处一起回来", async () => {
    apiMocks.listWorkflowRuns.mockResolvedValue(RUNS);
    apiMocks.listJobEvents.mockImplementation(async (jobId: string) => events(jobId));
    await renderEditor(CHAIN);
    await waitFor(() => expect(llmShows("success")).toBe(true), SLOW);
    expect(document.querySelector("[data-wf-viewing-past-run]")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "wfHistory" }));
    fireEvent.click((await screen.findByText("较早一次", undefined, SLOW)).closest("button")!);
    await waitFor(() => expect(llmShows("destructive")).toBe(true), SLOW);
    expect(screen.getByText("较早一次").closest("button")!.getAttribute("aria-current")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "wfBackToLatestRun" }));
    await waitFor(() => expect(llmShows("success")).toBe(true), SLOW);
    expect(screen.getByText("最新一次").closest("button")!.getAttribute("aria-current")).toBe("true");
    expect(document.querySelector("[data-wf-viewing-past-run]")).toBeNull();
  }, SLOW_TEST);
});

describe("循环体里的就绪问题", () => {
  const BROKEN_BODY = (() => {
    const graph = structuredClone(LOOPED);
    ((graph.nodes[1].config!.body as WorkflowGraph).nodes[0].config as Record<string, unknown>).template = "";
    return graph;
  })();
  const badgeOf = (id: string) => nodeEl(id).querySelector('[aria-label="wfIssueRequired"]');

  it("主流程上挂在循环节点头上;点清单那一条,进到循环体、选中出问题的那个节点,它身上也有角标", async () => {
    await renderEditor(BROKEN_BODY);
    await waitFor(() => expect(badgeOf("loop-1")).not.toBeNull(), SLOW);

    fireEvent.click(screen.getByRole("button", { name: /^wfChecklist:/ }));
    //: 没起名的循环按它的显示名叫(registry 的 label),和后端运行前检查说的是同一个名字。
    fireEvent.click(await screen.findByText("loop › 体内", undefined, SLOW));
    const trail = screen.getByRole("navigation", { name: "page-trail" });
    await waitFor(() => expect(within(trail).getByText("loop · wfLoopBody").getAttribute("aria-current")).toBe("page"), SLOW);
    await waitFor(() => expect(nodeEl("template-1").className).toContain("selected"), SLOW);
    expect(badgeOf("template-1")).not.toBeNull();
  }, SLOW_TEST);
});

describe("查找节点", () => {
  //: 此前只搜画布正在显示的那一层,也不认节点 id —— 站在主流程上找不到循环体里的节点,
  //: 而运行报错、就绪清单说的恰恰是 id。
  it("站在主流程上按 id 搜到循环体里的节点;点它进到循环体并选中它", async () => {
    await renderEditor(LOOPED);
    await waitFor(() => nodeEl("loop-1"));
    fireEvent.click(screen.getByRole("button", { name: "wfNodeSearch" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "wfNodeSearch" }), { target: { value: "template-1" } });
    const hit = await screen.findByText("体内");
    expect(hit.closest("button")!.textContent).toContain("loop");
    fireEvent.click(hit.closest("button")!);
    const trail = screen.getByRole("navigation", { name: "page-trail" });
    await waitFor(() => expect(within(trail).getByText("loop · wfLoopBody").getAttribute("aria-current")).toBe("page"), SLOW);
    await waitFor(() => expect(nodeEl("template-1").className).toContain("selected"), SLOW);
  }, SLOW_TEST);
});

describe("工作流列表", () => {
  const PLAIN: WorkflowGraph = {
    nodes: [
      { id: "start", type: "start", position: { x: 0, y: 0 }, config: {} },
      { id: "template-1", type: "template", position: { x: 200, y: 0 }, config: { template: "hi" } },
    ],
    edges: [{ id: "e", source: "start", target: "template-1" }],
  } as WorkflowGraph;

  async function renderList(workflows: ReturnType<typeof workflowWith>[]) {
    localStorage.removeItem("mosael:selected:workflows");
    apiMocks.listWorkflows.mockResolvedValue(workflows);
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
    await screen.findAllByText("测试");
  }
  const menuItems = () => screen.getAllByRole("menuitem").map((item) => item.textContent?.trim());

  //: 和编辑器的运行键同一个判据:同一张图在编辑器里跑不了,在列表上也不该排进队列。
  it("卡片右键「运行」:有阻断问题就不发请求,说清卡在哪,给一个去编辑器看的出口", async () => {
    const broken = structuredClone(PLAIN);
    broken.nodes[1].config = { template: "" };
    await renderList([workflowWith(broken)]);
    fireEvent.contextMenu(screen.getByText("测试"), { clientX: 10, clientY: 10 });
    fireEvent.click(screen.getByRole("menuitem", { name: "wfRun" }));
    await waitFor(() => expect(toastMocks.error).toHaveBeenCalled());
    expect(apiMocks.runWorkflow).not.toHaveBeenCalled();
    const [text, options] = toastMocks.error.mock.calls[0] as [string, { action: { label: string; onClick: () => void } }];
    expect(text).toBe("wfRunBlockedInList");
    expect(options.action.label).toBe("wfOpenEditorToFix");
    act(() => options.action.onClick());
    await screen.findByRole("group", { name: "canvasTools" }, { timeout: 10000 });
  });

  it("卡片右键「运行」:判过没问题才发请求", async () => {
    await renderList([workflowWith(PLAIN)]);
    fireEvent.contextMenu(screen.getByText("测试"), { clientX: 10, clientY: 10 });
    fireEvent.click(screen.getByRole("menuitem", { name: "wfRun" }));
    await waitFor(() => expect(apiMocks.runWorkflow).toHaveBeenCalledWith("wf1"));
    expect(toastMocks.success).toHaveBeenCalledWith("wfRunQueued");
  });

  //: 和时间线同一条规则:右键的那张在选区里就作用于整个选区,只给能对一批做的动作。
  it("多选时右键选区里的一张:只给批量删除;右键选区外的一张:是它自己的菜单", async () => {
    await renderList([workflowWith(PLAIN), { ...workflowWith(PLAIN), id: "wf2", name: "另一个" }]);
    fireEvent.click(screen.getByRole("button", { name: "mediaSelectMode" }));
    fireEvent.click(screen.getByRole("button", { name: "测试" }));
    fireEvent.click(screen.getByRole("button", { name: "另一个" }));
    fireEvent.contextMenu(screen.getByText("测试"), { clientX: 10, clientY: 10 });
    expect(menuItems()).toEqual(["deleteSelectedN"]);
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });

    fireEvent.click(screen.getByRole("button", { name: "另一个" }));
    fireEvent.contextMenu(screen.getByText("另一个"), { clientX: 10, clientY: 10 });
    expect(menuItems()).toEqual(["wfRun", "rename", "wfExport", "delete"]);
  });
});

describe("从别处打开某一次运行", () => {
  //: 浏览器自动化的悬浮卡片点标题跳过来:选中那条工作流、执行历史打开并停在那一次 —— 不是最近那次。
  it("打开那条工作流,执行历史停在指定的那一次", async () => {
    const { emitOpenEvent, OPEN_WORKFLOW_RUN, workflowRunLink } = await import("@/lib/deepLink");
    apiMocks.listWorkflowRuns.mockResolvedValue([
      { id: "job-new", kind: "workflow", status: "running", message: "最新一次", created_at: "2026-09-19T05:00:00", updated_at: "2026-09-19T05:00:10", payload: {} },
      { id: "job-old", kind: "workflow", status: "succeeded", message: "较早一次", created_at: "2026-09-19T04:00:00", updated_at: "2026-09-19T04:00:10", payload: {} },
    ]);
    localStorage.removeItem("mosael:selected:workflows");
    act(() => emitOpenEvent(OPEN_WORKFLOW_RUN, workflowRunLink("wf1", "job-old")));
    await renderEditor({ nodes: [{ id: "start", type: "start", position: { x: 0, y: 0 }, config: { params: {} } }], edges: [] });

    const older = (await screen.findByText("较早一次")).closest("button")!;
    expect(older.getAttribute("aria-current")).toBe("true");
    expect(screen.getByText("最新一次").closest("button")!.getAttribute("aria-current")).toBeNull();
    await waitFor(() => expect(apiMocks.listJobEvents).toHaveBeenCalledWith("job-old"));
  });
});
