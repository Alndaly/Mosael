import vm from "node:vm";

import { describe, expect, it, vi } from "vitest";

import {
  MAX_EVENTS,
  SAVE_COMMAND,
  WORKBENCH_VERSION,
  parseWorkbenchExport,
  parseWorkbenchPoll,
  parseWorkbenchResult,
  workbenchCallScript,
  workbenchInstallScript,
  workbenchPollScript,
  type WorkbenchCall,
} from "./comfyWorkbench";

const ORIGIN = "http://192.168.3.15:8188";

interface FakeWidget {
  name: string;
  type: string;
  value: unknown;
  options: { values?: unknown };
  setValue?: (value: unknown, context: unknown) => void;
}

/**
 * 一页假的 ComfyUI 前端:只有桥碰得到的那几样 —— 画布(选中的节点、当前那层图)、根图、`api`(EventTarget 那样挂监听、
 * clientId)、工作流仓库(开着的那张、改动跟踪)、命令仓库、`refreshComboInNodes`、`graphToPrompt`。
 */
function comfyPage(origin = ORIGIN) {
  const listeners = new Map<string, ((event: { detail: unknown }) => void)[]>();
  const api = {
    clientId: "4f1c0e2a9b7d4c51a3e8",
    addEventListener: (type: string, listener: (event: { detail: unknown }) => void) =>
      listeners.set(type, [...(listeners.get(type) ?? []), listener]),
  };
  const fire = (type: string, detail: unknown) => listeners.get(type)?.forEach((listener) => listener({ detail }));
  const tracker = { captureCanvasState: vi.fn(), activeState: { nodes: [] } as unknown };
  const active = { path: "workflows/人像/古风.json", filename: "古风", isTemporary: false, isModified: true, changeTracker: tracker };
  const ckpt: FakeWidget = {
    name: "ckpt_name", type: "combo", value: "a.safetensors",
    options: { values: ["a.safetensors", "sdxl\\b.safetensors"] },
  };
  ckpt.setValue = vi.fn((value: unknown) => {
    ckpt.value = value;
  });
  const loader = { id: 4, type: "CheckpointLoaderSimple", comfyClass: "CheckpointLoaderSimple", title: "Load Checkpoint",
                   properties: {} as Record<string, unknown>, widgets: [ckpt] };
  const steps: FakeWidget = { name: "steps", type: "number", value: 20, options: {} };
  const sampler = { id: 3, type: "KSampler", title: "KSampler", properties: { mosael: { result: true } } as Record<string, unknown>,
                    widgets: [steps], onWidgetChanged: vi.fn() };
  const save = { id: 9, type: "SaveImage", title: "Save", properties: {} as Record<string, unknown>, widgets: [] };
  //: 一张子图(根图上节点 12 是它的实例),里面一个 LoRA 加载节点 5
  const inner = { id: 5, type: "LoraLoader", title: "LoRA", properties: {} as Record<string, unknown>, widgets: [] };
  const subgraph = { id: "8f1c0e2a-9b7d-4c51", name: "细节", nodes: [inner] };
  const graph = { nodes: [loader, sampler, save], extra: { ue_links: [] } as Record<string, unknown>, setDirtyCanvas: vi.fn(),
                  subgraphs: new Map([[subgraph.id, subgraph]]) };
  const execute = vi.fn(async () => undefined);
  const app = {
    api,
    canvas: {
      graph: graph as unknown,
      selected_nodes: {} as Record<string, unknown>,
      deselectAll: vi.fn(),
      selectItems: vi.fn(),
      centerOnNode: vi.fn(),
      setDirty: vi.fn(),
      openSubgraph: vi.fn(function (this: { graph: unknown }, next: unknown) { this.graph = next; }),
      setGraph: vi.fn(function (this: { graph: unknown }, next: unknown) { this.graph = next; }),
    },
    graph,
    rootGraph: graph,
    refreshComboInNodes: vi.fn(async () => undefined),
    graphToPrompt: vi.fn(async () => ({
      workflow: { nodes: [{ id: 4 }, { id: 3 }], links: [], extra: {} },
      output: { "3": { class_type: "KSampler", inputs: { steps: 20 } } },
    })),
    extensionManager: {
      workflow: { activeWorkflow: active },
      command: { commands: [{ id: SAVE_COMMAND }, { id: "Comfy.NewBlankWorkflow" }], execute },
    },
  };
  const window: Record<string, unknown> = { app };
  const context = vm.createContext({ window, location: { origin } });
  const run = <T = unknown>(script: string) => vm.runInContext(script, context) as Promise<T> | T;
  return { app, window, fire, tracker, active, ckpt, steps, loader, sampler, save, graph, subgraph, inner, execute, run };
}

async function installed(page = comfyPage()) {
  expect(await page.run(workbenchInstallScript(ORIGIN))).toBe("installed");
  return page;
}

const call = (page: ReturnType<typeof comfyPage>, one: WorkbenchCall) => page.run(workbenchCallScript(ORIGIN, one));

describe("工作台的桥(注入的脚本)", () => {
  it("注入一次;同一版已经在就不再注入;页面自己占了这个名字(或别的版本)就当桥不在", async () => {
    const page = await installed();
    expect(await page.run(workbenchInstallScript(ORIGIN))).toBe("present");
    const bridge = page.window.__mosaelWorkbench as { version: number };
    expect(bridge.version).toBe(WORKBENCH_VERSION);
    expect(Object.isFrozen(bridge), "页面里的脚本改不了它的方法").toBe(true);
    const taken = comfyPage();
    taken.window.__mosaelWorkbench = { version: 0 };
    expect(await taken.run(workbenchInstallScript(ORIGIN))).toBe("conflict");
    expect(await call(taken, { op: "save" })).toEqual({ error: "missing" });
  });

  it("视图停在别的站点、前端还没起来:不注入,调用什么都不做", async () => {
    const elsewhere = comfyPage("https://example.com");
    expect(await elsewhere.run(workbenchInstallScript(ORIGIN))).toBe("elsewhere");
    expect(await call(elsewhere, { op: "save" })).toEqual({ error: "elsewhere" });
    expect(elsewhere.execute).not.toHaveBeenCalled();
    const early = comfyPage();
    delete (early.window as { app?: unknown }).app;
    expect(await early.run(workbenchInstallScript(ORIGIN))).toBe("notReady");
  });

  it("轮询:能力、开着的那张(路径、有没有没存的改动)、选中的一个节点(类型、widget 名字和值、是不是下拉)、clientId", async () => {
    const page = await installed();
    page.app.canvas.selected_nodes = { 4: page.loader };
    const raw = await page.run(workbenchPollScript(ORIGIN));
    expect(raw).toEqual({
      version: WORKBENCH_VERSION,
      capabilities: { selection: true, setWidget: true, refreshCombos: true, export: true, dirty: true, save: true, events: true,
                      marks: true, changes: true, locate: true, subgraphs: true },
      workflow: { path: "workflows/人像/古风.json", name: "古风", temporary: false, modified: true, revision: 1 },
      selection: { count: 1, node: { id: "4", type: "CheckpointLoaderSimple", title: "Load Checkpoint", widgets: [
        { name: "ckpt_name", type: "combo", value: "a.safetensors", combo: true }] } },
      clientId: "4f1c0e2a9b7d4c51a3e8",
      events: [],
    });
    page.app.canvas.selected_nodes = { 4: page.loader, 3: page.sampler };
    expect(((await page.run(workbenchPollScript(ORIGIN))) as { selection: unknown }).selection,
           "选中好几个就只报个数").toEqual({ count: 2, node: null });
  });

  it("开着的是哪一张、改过几回:改动跟踪换了一份图就加一,选中节点不算;换一张也加一", async () => {
    const page = await installed();
    const workflow = async () => ((await page.run(workbenchPollScript(ORIGIN))) as { workflow: { path: string; revision: number } })
      .workflow;
    const first = await workflow();
    expect(first.revision).toBe(1);
    page.app.canvas.selected_nodes = { 4: page.loader };
    expect((await workflow()).revision, "选中节点不算改动").toBe(1);
    page.tracker.activeState = { nodes: [{ id: 4 }] };
    expect((await workflow()).revision, "前端认了一次改动").toBe(2);
    expect((await workflow()).revision).toBe(2);
    // 在 ComfyUI 的标签栏里换到另一张(没存过的)
    page.app.extensionManager.workflow.activeWorkflow = { ...page.active, path: "workflows/Unsaved Workflow (2).json",
      filename: "Unsaved Workflow (2)", isTemporary: true, changeTracker: { ...page.tracker, activeState: {} } };
    expect(await workflow()).toMatchObject({ path: "workflows/Unsaved Workflow (2).json", revision: 3 });
  });

  it("定位节点:选中、移到画面中间;在子图里的先进那张子图;这版前端进不了子图就说在子图里", async () => {
    const page = await installed();
    const canvas = page.app.canvas;
    expect(await call(page, { op: "locate", node: "4", subgraph: null })).toEqual({ ok: true });
    expect(canvas.selectItems).toHaveBeenLastCalledWith([page.loader]);
    expect(canvas.centerOnNode).toHaveBeenLastCalledWith(page.loader);
    expect(await call(page, { op: "locate", node: "5", subgraph: page.subgraph.id })).toEqual({ ok: true });
    expect(canvas.openSubgraph).toHaveBeenCalledWith(page.subgraph);
    expect(canvas.centerOnNode).toHaveBeenLastCalledWith(page.inner);
    // 停在子图里时定位根图上的节点:先回根图
    expect(await call(page, { op: "locate", node: "9", subgraph: null })).toEqual({ ok: true });
    expect(canvas.setGraph).toHaveBeenLastCalledWith(page.graph);
    expect(canvas.centerOnNode).toHaveBeenLastCalledWith(page.save);
    expect(await call(page, { op: "locate", node: "77", subgraph: null })).toEqual({ error: "noNode" });
    expect(await call(page, { op: "locate", node: "5", subgraph: "nope" })).toEqual({ error: "noNode" });
    const old = comfyPage();
    delete (old.app.canvas as { openSubgraph?: unknown }).openSubgraph;
    await installed(old);
    expect(await call(old, { op: "locate", node: "5", subgraph: old.subgraph.id })).toEqual({ error: "inSubgraph" });
    expect(((await old.run(workbenchPollScript(ORIGIN))) as { capabilities: Record<string, boolean> }).capabilities)
      .toMatchObject({ locate: true, subgraphs: false });
    expect(parseWorkbenchResult({ op: "locate", node: "5", subgraph: "x" }, { error: "inSubgraph" }))
      .toEqual({ ok: false, error: "inSubgraph" });
  });

  it("这版前端缺的东西在能力表里是 false(面板据此说不支持),画布照样是 ComfyUI", async () => {
    const page = comfyPage();
    const app = page.app as Record<string, unknown>;
    delete app.refreshComboInNodes;
    delete app.graphToPrompt;
    page.app.extensionManager.command.commands = [];
    (page.app as { api: unknown }).api = undefined;
    await installed(page);
    const raw = (await page.run(workbenchPollScript(ORIGIN))) as { capabilities: Record<string, boolean> };
    expect(raw.capabilities).toMatchObject({ refreshCombos: false, export: false, save: false, events: false, selection: true });
  });

  it("跑的事件进一个有上限的队列,取一次清一次;形状不对的事件丢掉", async () => {
    const page = await installed();
    page.fire("executing", { node: "3", display_node: "3", prompt_id: "p1" });
    page.fire("progress", { value: 4, max: 20, prompt_id: "p1", node: "3" });
    page.fire("execution_error", { prompt_id: "p1", node_id: "8", node_type: "VAEDecode", exception_message: "OOM" });
    page.fire("executed", null);
    const first = (await page.run(workbenchPollScript(ORIGIN))) as { events: Record<string, unknown>[] };
    expect(first.events.map(({ at: _at, ...rest }) => rest)).toEqual([
      { type: "executing", promptId: "p1", node: "3" },
      { type: "progress", promptId: "p1", node: "3", value: 4, max: 20 },
      { type: "execution_error", promptId: "p1", node: "8", nodeType: "VAEDecode", message: "OOM" },
    ]);
    expect(((await page.run(workbenchPollScript(ORIGIN))) as { events: unknown[] }).events).toEqual([]);
    for (let index = 0; index < MAX_EVENTS + 50; index += 1) page.fire("progress", { value: index, max: 999, prompt_id: "p2" });
    const bounded = (await page.run(workbenchPollScript(ORIGIN))) as { events: { value: number }[] };
    expect(bounded.events).toHaveLength(MAX_EVENTS);
    expect(bounded.events[0].value, "满了丢最老的").toBe(50);
  });

  it("填值:先查它在下拉里(Windows 上的反斜杠路径也认),经 widget 自己的 setValue 填,改动跟踪记一笔", async () => {
    const page = await installed();
    expect(await call(page, { op: "setWidget", node: "4", widget: "ckpt_name", value: "sdxl/b.safetensors" }))
      .toEqual({ ok: true, value: "sdxl\\b.safetensors" });
    expect(page.ckpt.setValue).toHaveBeenCalledWith("sdxl\\b.safetensors", expect.objectContaining({ node: page.loader }));
    expect(page.tracker.captureCanvasState).toHaveBeenCalled();
    expect(await call(page, { op: "setWidget", node: "4", widget: "ckpt_name", value: "gone.safetensors" }))
      .toEqual({ error: "notInList" });
    expect(page.ckpt.value).toBe("sdxl\\b.safetensors");
    expect(await call(page, { op: "setWidget", node: "77", widget: "ckpt_name", value: "a" })).toEqual({ error: "noNode" });
    expect(await call(page, { op: "setWidget", node: "4", widget: "nope", value: "a" })).toEqual({ error: "noWidget" });
    expect(await call(page, { op: "setWidget", node: "3", widget: "steps", value: 30 })).toEqual({ ok: true, value: 30 });
    expect(page.sampler.onWidgetChanged, "没有 setValue 的老 widget:直接写值、照样通知节点").toHaveBeenCalledWith("steps", 30, 20,
      page.steps);
  });

  it("widget 名字和值经 JSON 编码:带引号、像脚本的也只是数据", async () => {
    const page = await installed();
    const tricky = '"); window.hacked = true; ("';
    expect(await call(page, { op: "setWidget", node: "4", widget: tricky, value: tricky })).toEqual({ error: "noWidget" });
    expect(await call(page, { op: "setWidget", node: "4", widget: "ckpt_name", value: tricky })).toEqual({ error: "notInList" });
    expect(page.window.hacked).toBeUndefined();
  });

  it("刷新下拉、导出(界面格式 + API 格式 + clientId)、保存(前端自己的命令,不等它)", async () => {
    const page = await installed();
    expect(await call(page, { op: "refreshCombos" })).toEqual({ ok: true });
    expect(page.app.refreshComboInNodes).toHaveBeenCalledOnce();
    expect(await call(page, { op: "export" })).toEqual({
      workflow: { nodes: [{ id: 4 }, { id: 3 }], links: [], extra: {} },
      prompt: { "3": { class_type: "KSampler", inputs: { steps: 20 } } },
      clientId: "4f1c0e2a9b7d4c51a3e8",
    });
    expect(await call(page, { op: "save" })).toEqual({ ok: true });
    expect(page.execute).toHaveBeenCalledWith(SAVE_COMMAND);
  });

  it("写标记:清单里的节点换上 `properties.mosael`,别的节点上的去掉,图上的 `extra.mosael` 换掉;别的键不动", async () => {
    const page = await installed();
    const marks = { nodes: { "4": { expose: { ckpt_name: { order: 0, label: "模型" } } } },
                    extra: { version: 1, app: { title: "人像" } } };
    expect(await call(page, { op: "setMarks", marks })).toEqual({ ok: true });
    expect(page.loader.properties.mosael).toEqual(marks.nodes["4"]);
    expect("mosael" in page.sampler.properties, "不在清单里的节点:标记摘掉").toBe(false);
    expect(page.graph.extra).toEqual({ ue_links: [], mosael: marks.extra });
    expect(page.tracker.captureCanvasState).toHaveBeenCalled();
    expect(await call(page, { op: "setMarks", marks: { nodes: {}, extra: null } })).toEqual({ ok: true });
    expect(page.graph.extra).toEqual({ ue_links: [] });
    expect(await call(page, { op: "setMarks", marks: { nodes: { "99": { result: true } }, extra: null } }))
      .toEqual({ error: "noNode", nodes: ["99"] });
  });

  it("桥上的方法抛了错:说「没成」和原话,不把异常抛给主进程", async () => {
    const page = await installed();
    page.app.graphToPrompt.mockRejectedValueOnce(new Error("graph is broken"));
    expect(await call(page, { op: "export" })).toEqual({ error: "failed", message: "graph is broken" });
  });
});

describe("页面交回来的一律当提示:规整", () => {
  const poll = (overrides: Record<string, unknown> = {}) => ({
    version: WORKBENCH_VERSION,
    capabilities: { selection: true, setWidget: true, refreshCombos: true, export: true, dirty: true, save: true, events: true,
                    marks: true, changes: true, locate: true, subgraphs: false, extra: true },
    workflow: { path: "workflows/人像/古风.json", name: "古风", temporary: false, modified: true, revision: 7 },
    selection: { count: 1, node: { id: "4", type: "CheckpointLoaderSimple", title: "x", widgets: [
      { name: "ckpt_name", type: "combo", value: "a.safetensors", combo: true }, { name: "", value: 1 },
      { name: "bad", value: { evil: true } }] } },
    clientId: "4f1c0e2a9b7d4c51a3e8",
    events: [{ type: "progress", at: 1, promptId: "p1", node: "3", value: 4, max: 20, extra: "x" },
             { type: "eval", at: 1 }, "x"],
    ...overrides,
  });

  it("认得的才留:能力只认那几样、widget 的值只收标量、事件只认那几种", () => {
    const state = parseWorkbenchPoll(poll())!;
    expect(Object.keys(state.capabilities)).not.toContain("extra");
    expect(state.workflow).toEqual({ path: "人像/古风.json", name: "古风", temporary: false, modified: true,
                                     key: "workflows/人像/古风.json", revision: 7 });
    expect(state.capabilities).toMatchObject({ changes: true, locate: true, subgraphs: false });
    expect(state.selection.node!.widgets).toEqual([
      { name: "ckpt_name", type: "combo", value: "a.safetensors", combo: true },
      { name: "bad", type: "", value: null, combo: false },
    ]);
    expect(state.events).toEqual([{ type: "progress", at: 1, promptId: "p1", node: "3", value: 4, max: 20 }]);
  });

  it("形状不对、版本不对就当这一拍没看到;没存过的(前端的临时路径)路径是空的", () => {
    expect(parseWorkbenchPoll(null)).toBeNull();
    expect(parseWorkbenchPoll(poll({ version: 99 }))).toBeNull();
    expect(parseWorkbenchPoll(poll({ capabilities: "all" }))).toBeNull();
    expect(parseWorkbenchPoll(poll({ workflow: { path: "workflows/Unsaved Workflow (2).json", name: "Unsaved Workflow (2)",
                                                 temporary: true, revision: "x" } }))!.workflow,
           "没存过的:不能当路径用,但认得出是哪一张")
      .toEqual({ path: "", name: "Unsaved Workflow (2)", temporary: true, modified: false,
                 key: "workflows/Unsaved Workflow (2).json", revision: 0 });
    expect(parseWorkbenchPoll(poll({ workflow: { path: "../../etc/x.json" } }))!.workflow!.path).toBe("");
    expect(parseWorkbenchPoll(poll({ clientId: "a b;c" }))!.clientId).toBe("");
    expect(parseWorkbenchPoll(poll({ selection: { count: 1, node: { id: "x;y", widgets: [] } } }))!.selection.node).toBeNull();
  });

  it("导出:界面格式要有 nodes、API 图每个节点要有 class_type 和 inputs", () => {
    const good = { workflow: { nodes: [] }, prompt: { "3": { class_type: "KSampler", inputs: {} } }, clientId: "abc" };
    expect(parseWorkbenchExport(good)).toEqual(good);
    expect(parseWorkbenchExport({ ...good, workflow: {} })).toBeNull();
    expect(parseWorkbenchExport({ ...good, prompt: { "3": { class_type: "KSampler" } } })).toBeNull();
    expect(parseWorkbenchExport({ ...good, clientId: "x y" })!.clientId).toBe("");
    expect(parseWorkbenchResult({ op: "export" }, { workflow: {} })).toEqual({ ok: false, error: "failed", message: "malformed export" });
    expect(parseWorkbenchResult({ op: "save" }, { error: "weird" })).toEqual({ ok: false, error: "failed" });
    expect(parseWorkbenchResult({ op: "setWidget", node: "4", widget: "w", value: "v" }, { ok: true, value: { x: 1 } }))
      .toEqual({ ok: true, value: null });
  });
});
