/** @vitest-environment jsdom */

/**
 * ComfyUI 工作台(ADR 0038 §3、§6):画布是那台 ComfyUI 自己的(内嵌视图,这里看不见),Mosael 的顶栏和右边那一列画在旁边。
 * 主进程的桥报来的东西(开着的是哪一张、选中、脏标记、能力、事件)经 `onComfyWorkbench` 到这里;面板要桥做的事经
 * `comfyWorkbench` 交回去。这里看的是:
 *
 * - 顶栏:连接、工作流名、有没有没存的改动、操控方式、「保存」(前端自己的命令)、「运行」(没存过的不能跑,说为什么);
 *   右边那一列开着时网页让出那么宽,收起时还回去;会话结束(视图收起)就不画了;
 * - 模型库:选中一个加载节点 → 问插件那一格是哪个目录 → 只列那个目录的模型 → 点一个经桥填进去;下拉里还没有就给「刷新下拉」;
 *   那一格选的文件这台 ComfyUI 上没有 → 贴链接、认一下、就地确认后下载;
 * - 缺失项:导出画布(含没存的)交给插件认一遍,缺的节点包「装上」先就地确认;
 * - 应用:读画布上这张的应用表单,改了「写进画布」—— 插件算出标记、经桥改节点,不写文件;
 * - 运行与结果:跑画布上这张(导出的 API 图、界面格式、前端的 clientId),产出按来自的节点分组、标节点名,「只要这个节点的图」;
 * - 这版前端缺了哪一样,那一处说「不支持」,别的照常;
 * - 助手(ADR 0042):共用的智能体面板停靠在这一列里,页面上下文发送那一刻才取,回复里的 `#12` 点了在画布上定位。
 *
 * 版式、拉宽、换工作流、定位、找下载地址各有一组(在后面)。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getNodeFolders: vi.fn(),
  getModelLibrary: vi.fn(),
  getLocalNsfw: vi.fn(async () => ({ status: "missing", message: "", size_bytes: 22404720, pending: 0, scored: 0 })),
  installLocalNsfw: vi.fn(),
  getWorkflowLibrary: vi.fn(),
  resolveModelLink: vi.fn(),
  searchModelSources: vi.fn(),
  startModelDownload: vi.fn(),
  inspectWorkflowImport: vi.fn(),
  startNodeInstall: vi.fn(),
  rebootWorkflowServer: vi.fn(),
  getCanvasApp: vi.fn(),
  getCanvasMarks: vi.fn(),
  getFormUsages: vi.fn(),
  runCanvas: vi.fn(),
  refreshPluginInstance: vi.fn(),
  getJob: vi.fn(),
  cancelJob: vi.fn(),
  assetThumbnailUrl: (id: string) => `thumb://${id}`,
  assetPreviewUrl: (id: string) => `preview://${id}`,
  assetFileUrl: (id: string) => `file://${id}`,
  modelPreviewUrl: (_: string, folder: string, name: string) => `preview://${folder}/${name}`,
  modelThumbnailUrl: (_: string, folder: string, name: string) => `thumb://${folder}/${name}`,
}));
vi.mock("@/api/client", () => api);
vi.mock("@/app/preferences", async () => {
  //: 助手的页面上下文用真的中文文案拼(看得出填进去的是什么);别的照旧回键名
  const { messages } = await import("@/app/messages");
  const zh = messages["zh-CN"] as Record<string, string>;
  //: 「结果取自 {nodes}」留着占位:看得出填进去的节点名
  const t = (key: string) => (key === "workbenchRunResultsFrom" ? "workbenchRunResultsFrom {nodes}"
    : key.startsWith("workbenchAssistant") || key.startsWith("workbenchFixThis") ? zh[key] : key);
  return { useI18n: () => t, translateNow: t, usePreferences: () => ({ locale: "zh" }) };
});
//: 智能体面板本身另有测试(features/agent):这里换成一个记下参数、把「回复」交给真的 Markdown 渲染的替身;一次工具调用的
//: 结果交给这一页认得的画法(工具行怎么摆它见 features/agent 的 toolCallPageViews 测试)
const agent = vi.hoisted(() => ({ props: null as null | Record<string, unknown>, reply: "", tool: "", data: null as unknown }));
vi.mock("@/features/agent/CanvasAgentChat", async () => {
  const { AgentMarkdown } = await import("@/components/markdown/Markdown");
  const { AgentPageViewsContext } = await import("@/features/agent/pageViews");
  return {
    CanvasAgentChat: (props: Record<string, unknown>) => {
      agent.props = props;
      const views = React.useContext(AgentPageViewsContext);
      return (
        <div data-agent-chat="">
          {agent.reply && <AgentMarkdown>{agent.reply}</AgentMarkdown>}
          {agent.tool && views ? <div data-tool-result="">{views.toolResult(agent.tool, agent.data)}</div> : null}
        </div>
      );
    },
  };
});

import type { WorkflowApp } from "@/api/client";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { installAppChromeGuards } from "@/components/ui/appChrome";
import { resetNativeViewAside, settleNativeViewAside } from "@/components/ui/nativeViewAside";
import { comboFromEvent, listenKeys } from "@/lib/shortcuts";
import { HANDLE_COLUMN, HANDLE_ON_LEFT_EDGE } from "@/lib/useResizableSidebar";
import { declaresDrag, noDragAfter } from "@/test/dragRegions";
import { COLUMN_DEFAULT, COLUMN_MIN, DRAG_GUARD } from "./columnWidth";
import { FormsLockedError, markOnlyResult } from "./canvasMarks";
import { ComfyWorkbench } from "./ComfyWorkbench";
import { RECHECK_DELAY_MS } from "./MissingPanel";
import { openWorkbench, resetWorkbench } from "./workbenchSession";

const TARGET = { instanceId: "i1", instanceName: "ComfyUI · 192.168.3.15", workspaceId: "w1", url: "http://192.168.3.15:8188" };
const CAPS = { selection: true, setWidget: true, refreshCombos: true, export: true, dirty: true, save: true, events: true, marks: true,
               changes: true, locate: true, subgraphs: true, readGraph: true, applyOps: true, openWorkflow: true, toSubgraph: true,
               unpackSubgraph: true };
const LOADER = { id: "4", type: "CheckpointLoaderSimple", title: "Load Checkpoint",
                 widgets: [{ name: "ckpt_name", type: "combo", value: "sdxl.safetensors", combo: true }] };
const EXPORTED = {
  workflow: { nodes: [{ id: 4, type: "CheckpointLoaderSimple", widgets_values: ["sdxl.safetensors"] }, { id: 9, type: "SaveImage", title: "高清" },
                      { id: 17, type: "PreviewImage" }] },
  prompt: { "9": { class_type: "SaveImage", inputs: {} } },
  clientId: "4f1c0e2a9b7d4c51a3e8",
  at: { key: "workflows/人像/古风.json", revision: 1 },
};
const GUFENG = { path: "人像/古风.json", name: "古风", temporary: false, modified: true, key: "workflows/人像/古风.json", revision: 1 };

function state(overrides: Partial<ComfyWorkbenchState> = {}): ComfyWorkbenchState {
  return {
    capabilities: { ...CAPS },
    workflow: { ...GUFENG },
    selection: { count: 1, node: LOADER },
    clientId: EXPORTED.clientId,
    server: { comfyui: "0.39.0", frontend: "1.53.10" },
    events: [],
    renames: [],
    openedBy: null,
    ...overrides,
  };
}

/** 桌面版的几座桥:工作台的(开、做事、收到桥那边的)、页面工具的让位、顶栏的返回、视图亮没亮、大图让位、操控方式。 */
function desktop() {
  let listener: ((update: { connectionId: string; state: ComfyWorkbenchState | null }) => void) | null = null;
  let viewListener: ((view: { visible: boolean }) => void) | null = null;
  const comfyWorkbench = vi.fn(async ({ call }: { call: ComfyWorkbenchCall }) => {
    if (call.op === "export") return { ok: true, export: EXPORTED };
    if (call.op === "setWidget") return { ok: true, value: call.value };
    return { ok: true };
  });
  const bridges = {
    mosaelBrowser: {
      openComfyWorkbench: vi.fn(async () => ({ ok: true, outcome: "opened" })),
      comfyWorkbench,
      onComfyWorkbench: (callback: typeof listener) => {
        listener = callback;
        return () => (listener = null);
      },
      setComfyNavigation: vi.fn(async () => ({ ok: true, outcome: "applied" })),
    },
    mosaelPageTools: { setInset: vi.fn(async (_right: number) => undefined) },
    mosaelPublish: {
      hideView: vi.fn(async () => undefined),
      setOverlay: vi.fn(async (_up: boolean) => undefined),
      focusPage: vi.fn(async () => undefined),
      onViewState: (callback: typeof viewListener) => {
        viewListener = callback;
        return () => (viewListener = null);
      },
    },
  };
  for (const [name, value] of Object.entries(bridges)) vi.stubGlobal(name, value);
  const emit = (next: ComfyWorkbenchState | null) => act(() => listener?.({ connectionId: "i1", state: next }));
  const viewUp = (visible: boolean) => act(() => viewListener?.({ visible }));
  return { ...bridges, comfyWorkbench, emit, viewUp };
}

async function mount(first: ComfyWorkbenchState | null = state(), extra: React.ReactNode = null) {
  const bridge = desktop();
  await openWorkbench(TARGET, { path: "人像/古风.json" });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
        {extra}
        <ComfyWorkbench barHeight={56} />
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
  if (first) bridge.emit(first);
  return { ...bridge, view };
}

const calls = (bridge: { comfyWorkbench: ReturnType<typeof vi.fn> }) =>
  bridge.comfyWorkbench.mock.calls.map(([one]) => (one as { call: ComfyWorkbenchCall }).call);
const tab = (name: string) => fireEvent.click(screen.getByRole("tab", { name }));
const column = () => screen.getByRole("complementary", { name: "workbenchColumn" });
const shownPanel = () => column().querySelector<HTMLElement>("[role=tabpanel]:not([hidden])")!;

const appData = (overrides: Partial<WorkflowApp> = {}): WorkflowApp => ({
  path: "", modified: null, kind: "image", editable: true,
  items: [
    { key: "6.text", node: "6", input: "text", kind: "text", role: "prompt", title: "提示词", node_title: "", node_label: "CLIP 文本编码",
      hint: "", class_type: "CLIPTextEncode", common: true, media: "", folder: "", exposable: true, spec: { type: "string", default: "a girl" } },
    { key: "3.steps", node: "3", input: "steps", kind: "number", title: "步数", node_title: "采样", node_label: "采样", hint: "",
      class_type: "KSampler", common: true, role: "", media: "", folder: "", exposable: true, spec: { type: "integer", default: 20 } },
  ],
  outputs: [{ node: "9", title: "高清", label: "高清", class_type: "SaveImage", media: "image" },
            { node: "17", title: "", label: "PreviewImage", class_type: "PreviewImage", media: "image" }],
  app: { status: "none", version: "", upgradable: false, forms: [], results: [], invalid: 0, stray: 0 },
  ...overrides,
});

const SUCCEEDED = {
  id: "job-9", status: "succeeded", message: "", error: null,
  result: { asset_ids: ["a1", "a2", "a3"], output_parameters: [{ asset_id: "a1", parameters: { source_node: "17" } },
                                                              { asset_id: "a2", parameters: { source_node: "9" } },
                                                              { asset_id: "a3", parameters: { source_node: "17" } }] },
};

beforeEach(() => {
  window.localStorage.clear();
  for (const fn of Object.values(api)) if (typeof fn === "function" && "mockReset" in fn) (fn as ReturnType<typeof vi.fn>).mockReset();
  api.getNodeFolders.mockResolvedValue({ folders: ["checkpoints"] });
  api.getLocalNsfw.mockResolvedValue({ status: "missing", message: "", size_bytes: 22404720, pending: 0, scored: 0 });
  api.getModelLibrary.mockResolvedValue({
    folders: [], missing: [], downloads: [], download: { route: "local", note: "下到这台电脑上的 ComfyUI/models" },
    models: [
      { folder: "checkpoints", name: "sdxl.safetensors", family: "SDXL", title: "SDXL Base", triggers: [], has_preview: true },
      { folder: "checkpoints", name: "flux-dev.safetensors", family: "Flux", title: "", triggers: ["film grain"], has_preview: false },
      { folder: "checkpoints", name: "pony.safetensors", family: "SDXL", title: "Pony", triggers: [], has_preview: true },
      { folder: "loras", name: "style.safetensors", family: "SDXL", title: "", triggers: [], has_preview: false },
    ],
  });
  api.getWorkflowLibrary.mockResolvedValue({ workflows: [], manager: { version: "V4.0" } });
  api.inspectWorkflowImport.mockResolvedValue({ missing_nodes: [], missing_models: [] });
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

afterEach(async () => {
  // 大图、模型详情会让原生视图让开(components/ui/nativeViewAside 的模块级状态):先卸载、等那一串走完再重置,
  // 不然它带着上一条的「让开」进下一条(打乱顺序时「点缩略图打开大图」最后一次挪开 / 放回对不上)。
  cleanup();
  await settleNativeViewAside();
  resetNativeViewAside();
  resetWorkbench();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("ComfyUI 工作台", () => {
  it("顶栏:连接、工作流名、没存的改动;右边那一列开着时网页让出那么宽;会话结束就不画了", async () => {
    const bridge = await mount(null);
    expect(bridge.mosaelBrowser.openComfyWorkbench).toHaveBeenCalledWith({
      connectionId: "i1", url: TARGET.url, name: TARGET.instanceName, path: "人像/古风.json",
    });
    expect(screen.getAllByText("workbenchConnecting").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /workbenchRun/ }).hasAttribute("disabled"), "还没连上画布不能跑").toBe(true);
    bridge.emit(state());
    const bar = document.querySelector("[data-comfy-workbench-bar]") as HTMLElement;
    expect(within(bar).getByRole("heading").textContent).toBe("古风");
    expect(within(bar).getByText(TARGET.instanceName)).toBeTruthy();
    expect(within(bar).getByRole("img", { name: "workbenchUnsavedChanges" })).toBeTruthy();
    await waitFor(() => expect(bridge.mosaelPageTools.setInset).toHaveBeenLastCalledWith(COLUMN_DEFAULT));
    expect(within(column()).getAllByRole("tab").map((one) => one.textContent)).toEqual([
      "workbenchTabModels", "workbenchTabMissing", "workbenchTabApp", "workbenchTabRun", "workbenchTabAssistant",
    ]);
    fireEvent.click(within(bar).getByRole("button", { name: "workbenchColumnHide" }));
    await waitFor(() => expect(bridge.mosaelPageTools.setInset).toHaveBeenLastCalledWith(0));
    expect(screen.queryByRole("complementary", { name: "workbenchColumn" })).toBeNull();
    fireEvent.click(within(bar).getByRole("button", { name: "workbenchColumnShow" }));
    await waitFor(() => expect(bridge.mosaelPageTools.setInset).toHaveBeenLastCalledWith(COLUMN_DEFAULT));
    fireEvent.click(within(bar).getByRole("button", { name: /publishBackToApp/ }));
    expect(bridge.mosaelPublish.hideView).toHaveBeenCalled();
    bridge.emit(null);
    expect(document.querySelector("[data-comfy-workbench-bar]")).toBeNull();
  });

  it("在工作台里存好一张、或者工作台关上:这个连接的目录重拉 —— AI 工作台的右栏不再是存之前那张表", async () => {
    //: 维护者的路径:从 AI 工作台的「在工作台里打开」进来,在精简表单里加一项、存好、直接回去 —— 此前只有工作流库回来时才重拉。
    api.refreshPluginInstance.mockResolvedValue({});
    const bridge = await mount(state());
    expect(api.refreshPluginInstance, "还有没存的改动:不拉").not.toHaveBeenCalled();
    bridge.emit(state({ workflow: { ...GUFENG, revision: 2 } }));
    expect(api.refreshPluginInstance, "改着,还没存:不拉").not.toHaveBeenCalled();
    bridge.emit(state({ workflow: { ...GUFENG, modified: false, revision: 2 } }));
    await waitFor(() => expect(api.refreshPluginInstance).toHaveBeenCalledWith("i1"));
    expect(api.refreshPluginInstance).toHaveBeenCalledTimes(1);
    bridge.emit(state({ workflow: { ...GUFENG, key: "workflows/别的.json", modified: false } }));
    expect(api.refreshPluginInstance, "换了一张、它本来就存好的:不是存了一张").toHaveBeenCalledTimes(1);
    bridge.emit(null);
    await waitFor(() => expect(api.refreshPluginInstance).toHaveBeenCalledTimes(2));
  });

  it("保存是前端自己的保存命令;没存过的工作流不能在这里跑,说为什么", async () => {
    const bridge = await mount(state({ workflow: { path: "", name: "Unsaved Workflow", temporary: true, modified: true,
                                                   key: "workflows/Unsaved Workflow.json", revision: 1 } }));
    fireEvent.click(screen.getByRole("button", { name: /workbenchSave/ }));
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "save" }));
    //: 没存过的:ComfyUI 弹出起名字的框,键盘交给画布(不然打的字落在 Mosael 这边)
    await waitFor(() => expect(bridge.mosaelPublish.focusPage).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: /workbenchRun/ }).hasAttribute("disabled")).toBe(true);
    bridge.emit(state());
    fireEvent.click(screen.getByRole("button", { name: /workbenchSave/ }));
    await waitFor(() => expect(calls(bridge).filter((one) => one.op === "save")).toHaveLength(2));
    expect(bridge.mosaelPublish.focusPage, "存过的那张直接存,焦点不动").toHaveBeenCalledTimes(1);
  });

  it("⌘S / Ctrl+S:焦点在顶栏、右边这一列(助手的输入框里打着字也算)时和「保存」一样,只存一次、不往下传;落在别处的不管", async () => {
    //: 工作台底下那一页也认 ⌘S(比如工作流编辑器):它不该跟着存
    const underneath = vi.fn();
    const stop = listenKeys(window, (event) => {
      if (comboFromEvent(event) === "Mod+S") underneath();
    });
    const bridge = await mount(state(), <input aria-label="underneath" />);
    const saves = () => calls(bridge).filter((one) => one.op === "save").length;
    const composer = document.createElement("textarea");
    shownPanel().append(composer);
    fireEvent.keyDown(composer, { key: "s", code: "KeyS", metaKey: true });
    await waitFor(() => expect(saves()).toBe(1));
    fireEvent.keyDown(document.querySelector("[data-comfy-workbench-bar]")!, { key: "s", code: "KeyS", ctrlKey: true });
    await waitFor(() => expect(saves()).toBe(2));
    expect(underneath, "工作台接住了就不往下传").not.toHaveBeenCalled();
    fireEvent.keyDown(composer, { key: "s", code: "KeyS", metaKey: true, shiftKey: true });
    fireEvent.keyDown(composer, { key: "s", code: "KeyS" });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "underneath" }), { key: "s", code: "KeyS", metaKey: true });
    expect(saves(), "⇧⌘S、单按 S、落在工作台外面的都不算").toBe(2);
    expect(underneath).toHaveBeenCalledTimes(1);
    bridge.emit(state({ capabilities: { ...CAPS, save: false } }));
    fireEvent.keyDown(composer, { key: "s", code: "KeyS", metaKey: true });
    expect(saves(), "这版前端没有保存命令:接住,不存").toBe(2);
    expect(underneath).toHaveBeenCalledTimes(1);
    stop();
  });

  it("模型库:选中加载节点只列那个目录的模型,点一行经桥填进去;下拉里还没有就给「刷新下拉」", async () => {
    const bridge = await mount();
    await waitFor(() => expect(api.getNodeFolders).toHaveBeenCalledWith("i1", [
      { class_type: "CheckpointLoaderSimple", input: "ckpt_name" },
    ]));
    const list = await screen.findByRole("list", { name: "workbenchModelsList" });
    expect(within(list).getAllByRole("listitem").map((one) => one.textContent)).toEqual([
      expect.stringContaining("film grain"), expect.stringContaining("Pony"), expect.stringContaining("SDXL Base"),
    ]);
    expect(within(list).getByRole("button", { pressed: true }).textContent).toContain("SDXL Base");
    fireEvent.click(within(list).getByRole("button", { name: /film grain/ }));
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "setWidget", node: "4", widget: "ckpt_name", value: "flux-dev.safetensors" }));
    //: 填好了不另说一句(维护者:不要那句「已经把…填进画布上的这一格」);画布上那一格换了值,列表不回到「读取中」、不再问插件
    bridge.emit(state({ selection: { count: 1, node: { ...LOADER, widgets: [{ ...LOADER.widgets[0], value: "flux-dev.safetensors" }] } } }));
    await waitFor(() => expect(within(list).getByRole("button", { pressed: true }).textContent).toContain("film grain"));
    expect(within(column()).queryByRole("status")).toBeNull();
    expect(within(column()).queryByText("workbenchModelsLoading")).toBeNull();

    bridge.comfyWorkbench.mockImplementationOnce(async () => ({ ok: false, error: "notInList" }));
    fireEvent.click(within(list).getByRole("button", { name: /SDXL Base/ }));
    fireEvent.click(await screen.findByRole("button", { name: /workbenchCombosRefresh/ }));
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "refreshCombos" }));

    //: 换到同一种的另一个节点:同一句问题,用缓存的 —— 不回到「读取中」
    bridge.emit(state({ selection: { count: 1, node: { ...LOADER, id: "12" } } }));
    expect(within(column()).queryByText("workbenchModelsLoading")).toBeNull();
    expect(await screen.findByRole("list", { name: "workbenchModelsList" })).toBeTruthy();
    expect(api.getNodeFolders).toHaveBeenCalledTimes(1);
  });

  it("模型库:选中 CLIP 加载节点时,合它现在 type 的文本编码器排前面,不在配方里的排最后、标出来;换了 type 就地重排、不再问", async () => {
    const encoder = (name: string, kind: string, label: string) => ({
      folder: "text_encoders", name, family: "", family_source: "not_applicable", title: "", triggers: [], has_preview: false,
      encoder: { kind, label, source: "weights", pairs: [] },
    });
    api.getModelLibrary.mockResolvedValue({
      folders: [], missing: [], downloads: [],
      models: [encoder("a_clip_l.safetensors", "clip_l", "CLIP-L"), encoder("b_qwen.safetensors", "qwen3_06b", "Qwen3 0.6B"),
               encoder("c_umt5.safetensors", "umt5_xxl", "UMT5-XXL")],
    });
    api.getNodeFolders.mockImplementation(async (_: string, nodes: { input: string }[]) => ({
      folders: nodes.map((one) => (one.input === "clip_name" ? "text_encoders" : "")),
      encoders: nodes.map((one) => (one.input !== "clip_name" ? null : { type_widget: "type", by_type: {
        wan: { fits: ["umt5_xxl"], any_type: ["qwen3_06b"] },
        stable_diffusion: { fits: ["clip_l", "clip_h", "clip_g"], any_type: ["qwen3_06b"] },
      } })),
    }));
    const clip = (type: string) => ({ id: "5", type: "CLIPLoader", title: "Load CLIP", widgets: [
      { name: "clip_name", type: "combo", value: "c_umt5.safetensors", combo: true },
      { name: "type", type: "combo", value: type, combo: true },
    ] });
    const bridge = await mount(state({ selection: { count: 1, node: clip("wan") } }));
    const rows = async () => {
      const list = await screen.findByRole("list", { name: "workbenchModelsList" });
      return within(list).getAllByRole("listitem");
    };
    await waitFor(async () => expect((await rows()).map((one) => one.textContent?.includes("UMT5-XXL"))).toEqual([true, false, false]));
    const [first, middle, last] = await rows();
    expect(middle.textContent).toContain("Qwen3 0.6B");
    expect(middle.querySelector("[data-recipe-misfit]"), "ComfyUI 不看 type 的不算不合").toBeNull();
    expect(first.querySelector("[data-recipe-misfit]")).toBeNull();
    expect(last.textContent).toContain("CLIP-L");
    expect(last.querySelector("[data-recipe-misfit]")?.textContent).toBe("workbenchModelsNotInRecipe");

    bridge.emit(state({ selection: { count: 1, node: clip("stable_diffusion") } }));
    await waitFor(async () => expect((await rows())[0].textContent).toContain("CLIP-L"));
    expect(api.getNodeFolders, "配方是每一种 type 的,就地挑").toHaveBeenCalledTimes(1);
    expect(api.getNodeFolders).toHaveBeenLastCalledWith("i1", [
      { class_type: "CLIPLoader", input: "clip_name" }, { class_type: "CLIPLoader", input: "type" },
    ]);
    expect((await rows())[2].querySelector("[data-recipe-misfit]"), "UMT5-XXL 不在 stable_diffusion 的配方里").toBeTruthy();
  });

  it("模型库:缩略图照预览图那两组设置画(和模型库同一份,这里也能改),判成 NSFW 的带角标", async () => {
    window.localStorage.setItem("mosael:model-previews", JSON.stringify({ level: "clear", nsfw: "hidden" }));
    api.getModelLibrary.mockResolvedValue({
      folders: [], missing: [], downloads: [],
      models: [
        { folder: "checkpoints", name: "sdxl.safetensors", family: "SDXL", title: "SDXL Base", triggers: [], has_preview: true,
          nsfw: { flagged: false, manual: null, reasons: [] } },
        { folder: "checkpoints", name: "spicy.safetensors", family: "SDXL", title: "Spicy", triggers: [], has_preview: true,
          nsfw: { flagged: true, manual: null, reasons: [{ source: "metadata", nsfw: true, tags: ["nude"], words: [] }] } },
      ],
    });
    await mount();
    const list = await screen.findByRole("list", { name: "workbenchModelsList" });
    const item = (name: string) => within(list).getAllByRole("listitem").find((one) => one.textContent?.includes(name))!;
    expect(item("SDXL Base").querySelector("img")!.getAttribute("data-treatment")).toBe("clear");
    expect(item("Spicy").querySelector("img")).toBeNull();
    expect(item("Spicy").querySelector("[data-hidden-preview]")).toBeTruthy();
    expect(item("Spicy").querySelector("[data-nsfw-mark]")).toBeTruthy();
    fireEvent.click(within(column()).getByRole("button", { name: "modelPreviewSettings" }));
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "modelPreviewLevel" })).getByRole("radio", { name: "modelPreviewLevelHeavy" }));
    expect(item("SDXL Base").querySelector("img")!.getAttribute("data-treatment")).toBe("heavy");
    expect(JSON.parse(window.localStorage.getItem("mosael:model-previews")!)).toEqual({ level: "heavy", nsfw: "hidden" });
  });

  it("模型库:没选中节点时说怎么用;选的不是加载节点说一句;那一格的文件这台机器上没有就地下载(先确认)", async () => {
    const bridge = await mount(state({ selection: { count: 0, node: null } }));
    expect(within(column()).getByText("workbenchModelsPick")).toBeTruthy();
    api.getNodeFolders.mockResolvedValue({ folders: [""] });
    bridge.emit(state({ selection: { count: 1, node: { ...LOADER, id: "3", type: "KSampler", title: "采样" } } }));
    expect(await within(column()).findByText("workbenchModelsNoSlot")).toBeTruthy();

    api.getNodeFolders.mockResolvedValue({ folders: ["checkpoints"] });
    bridge.emit(state({ selection: { count: 1, node: { ...LOADER, widgets: [{ ...LOADER.widgets[0], value: "gone.safetensors" }] } } }));
    expect(await within(column()).findByText("workbenchModelsMissing")).toBeTruthy();
    api.resolveModelLink.mockResolvedValue({ source: "huggingface", url: "https://huggingface.co/a/b/resolve/main/gone.safetensors",
                                             filename: "gone.safetensors", exists: false, uses_token: false, note: "" });
    api.startModelDownload.mockResolvedValue({ id: "job-1", status: "queued" });
    api.getJob.mockResolvedValue({ id: "job-1", status: "running", message: "1.2 MB" });
    fireEvent.change(screen.getByRole("textbox", { name: "workbenchDownloadLink" }), {
      target: { value: "https://huggingface.co/a/b/blob/main/gone.safetensors" },
    });
    fireEvent.click(screen.getByRole("button", { name: /workbenchDownloadResolve/ }));
    const confirm = await screen.findByRole("group", { name: "workbenchDownloadConfirm" });
    expect(within(confirm).getByText("下到这台电脑上的 ComfyUI/models"), "确认里写着这台服务器下载走哪条路").toBeTruthy();
    expect(api.startModelDownload, "确认之前不下").not.toHaveBeenCalled();
    fireEvent.click(within(confirm).getByRole("button", { name: /workbenchDownloadStart/ }));
    await waitFor(() => expect(api.startModelDownload).toHaveBeenCalledWith("i1", {
      workspace_id: "w1", url: "https://huggingface.co/a/b/resolve/main/gone.safetensors", folder: "checkpoints", filename: "gone.safetensors",
    }));
  });

  it("缺失项:导出画布(含没存的)让插件认一遍;缺的节点包「装上」先就地确认", async () => {
    const bridge = await mount();
    api.inspectWorkflowImport.mockResolvedValue({
      missing_nodes: [{ type: "CR Prompt Text", count: 2, packs: [{ id: "comfyroll", title: "Comfyroll", installed: false }] }],
      missing_models: [{ folder: "loras", name: "x.safetensors", url: "" }],
    });
    tab("workbenchTabMissing");
    await waitFor(() => expect(api.inspectWorkflowImport).toHaveBeenCalledWith("i1", { text: JSON.stringify(EXPORTED.workflow) }));
    expect(calls(bridge)).toContainEqual({ op: "export" });
    expect(await screen.findByText("CR Prompt Text")).toBeTruthy();
    expect(screen.getByRole("button", { name: "workbenchSearchSourcesLabel" }), "没写下载地址的:就地找、或者贴链接").toBeTruthy();
    api.startNodeInstall.mockResolvedValue({ id: "job-2", status: "queued" });
    api.getJob.mockResolvedValue({ id: "job-2", status: "running" });
    fireEvent.click(screen.getByRole("button", { name: "workbenchMissingInstallLabel" }));
    const confirm = screen.getByRole("group", { name: "workbenchInstallTitle" });
    fireEvent.click(within(confirm).getByRole("button", { name: /workbenchMissingInstall/ }));
    await waitFor(() => expect(api.startNodeInstall).toHaveBeenCalledWith("i1", { workspace_id: "w1", packs: ["comfyroll"] }));
  });

  it("表单:读画布上这张;新建一张、起名、挑项再「写进画布」—— 插件算标记、经桥改节点,不写文件;写完重读拿到新表单的 id", async () => {
    const bridge = await mount();
    api.getCanvasApp.mockResolvedValue(appData());
    const marks = { nodes: { "3": { forms: { k3x9a2: { steps: { order: 0 } } } } },
                    extra: { version: 2, forms: [{ id: "k3x9a2", title: "调步数" }] } };
    api.getCanvasMarks.mockResolvedValue(marks);
    tab("workbenchTabApp");
    await waitFor(() => expect(api.getCanvasApp).toHaveBeenCalledWith("i1", EXPORTED.workflow, "人像/古风.json"));
    await waitFor(() => expect(document.querySelector("[data-no-forms]")).toBeTruthy());
    expect(screen.queryByRole("button", { name: /workbenchAppWrite/ }), "一张表单都没有、也没改过:没东西可同步").toBeNull();
    //: 一张表单都没有:用的人看到的是完整工作流;「新表单」加一张空白的
    fireEvent.click(within(document.querySelector("[data-no-forms]") as HTMLElement).getByRole("button", { name: /workflowFormNew/ }));
    const write = await screen.findByRole("button", { name: /workbenchAppWrite/ });
    expect(write.hasAttribute("disabled"), "新表单还没起标题:写不了").toBe(true)
    fireEvent.change(screen.getByPlaceholderText("workflowAppNamePlaceholder"), { target: { value: "调步数" } });
    //: 面板窄:编辑器是「挑项 / 表单 / 预览」三个标签,先到「挑项」里点「+」
    fireEvent.mouseDown(await screen.findByRole("tab", { name: /workflowAppTabSource/ }));
    fireEvent.click(within(document.querySelector("[data-source-item='3.steps']") as HTMLElement)
      .getByRole("button", { name: "workflowAppAdd" }));
    api.getCanvasApp.mockResolvedValue(appData({ app: { status: "ok", version: "2", upgradable: false, results: [], invalid: 0,
                                                        stray: 0, forms: [{ id: "k3x9a2", title: "调步数", description: "",
                                                                            fields: 1, invalid: 0, model: "", tool: "",
                                                                            items: [] }] } }));
    fireEvent.click(write);
    await waitFor(() => expect(api.getCanvasMarks).toHaveBeenCalled());
    const [, body] = api.getCanvasMarks.mock.calls[0];
    expect(body.content).toEqual(EXPORTED.workflow);
    expect(body.forms).toHaveLength(1);
    expect(body.forms[0].id, "新表单不带 id:插件起").toBe("");
    expect(body.forms[0].title).toBe("调步数");
    expect(body.forms[0].items.map((one: { node: string; input: string }) => `${one.node}.${one.input}`)).toEqual(["3.steps"]);
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "setMarks", marks, expect: EXPORTED.at }));
    expect(await screen.findByText("workbenchAppWritten")).toBeTruthy();
    await waitFor(() => expect(api.getCanvasApp).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("button", { name: /workbenchAppWrite/ }).className,
                               "同步完了没东西可同步:不再是实心主按钮").not.toMatch(/\bbg-action\b/));
    expect(await screen.findByRole("tab", { name: "调步数" }), "重读之后:那张有了插件起的 id,还停在它").toBeTruthy();
    //: 桌面版真机走查:按了顶栏「保存」、画布报存好了,「已同步到画布,但还没保存」还挂着
    bridge.emit(state({ workflow: { ...GUFENG, modified: false, revision: 2 } }));
    await waitFor(() => expect(screen.queryByText("workbenchAppWritten"), "存好了:那句收起来").toBeNull());
  });

  //: 维护者 2026-10-09:「这里这个新表单的交互入口重复累赘了」—— 没有表单时上面那一排一颗、空状态里又一颗;顶上四行说明比空状态还重,
  //: 「同步到画布」没东西可同步时是一颗灰掉的实心主按钮
  it("表单:还没有表单时只有空状态里那一颗「新表单」,它是这一屏的焦点;有了表单入口回到表单那一排,说明和「同步到画布」才出来", async () => {
    await mount();
    api.getCanvasApp.mockResolvedValue(appData());
    tab("workbenchTabApp");
    const empty = await waitFor(() => {
      const found = document.querySelector("[data-no-forms]") as HTMLElement | null;
      expect(found).not.toBeNull();
      return found!;
    });
    const entries = within(shownPanel()).getAllByRole("button", { name: /workflowFormNew/ });
    expect(entries, "一屏只有一个「新表单」入口").toHaveLength(1);
    expect(empty.contains(entries[0]), "放在空状态里").toBe(true);
    expect(entries[0].className, "它是这一屏的焦点:实心主按钮").toMatch(/\bbg-action\b/);
    expect(shownPanel().querySelector("[data-forms-bar]"), "表单那一排还没有东西,不出来").toBeNull();
    expect(shownPanel().querySelector("[data-app-hint]"), "怎么同步、怎么存的说明这时还用不上").toBeNull();
    expect(within(shownPanel()).queryByRole("button", { name: /workbenchAppWrite/ }), "没东西可同步").toBeNull();

    fireEvent.click(entries[0]);
    await waitFor(() => expect(shownPanel().querySelector("[data-no-forms]")).toBeNull());
    expect(shownPanel().querySelector("[data-forms-bar] [data-forms-new]"), "有了表单:入口回到表单那一排").toBeTruthy();
    expect(within(shownPanel()).getAllByRole("button", { name: /workflowFormNew/ })).toHaveLength(1);
    expect(shownPanel().querySelector("[data-app-hint]")).toBeTruthy();
    const write = within(shownPanel()).getByRole("button", { name: /workbenchAppWrite/ });
    expect(write.hasAttribute("disabled")).toBe(true);
    expect(write.className, "新表单还没起标题、点不了:不是实心的(焦点在起标题、挑项)").not.toMatch(/\bbg-action\b/);
    fireEvent.change(screen.getByPlaceholderText("workflowAppNamePlaceholder"), { target: { value: "调步数" } });
    expect(write.className, "点得了:它成了主按钮").toMatch(/\bbg-action\b/);
  });

  //: 桌面版真机走查:确认框是普通弹窗(z-50)时,中间被画布盖着、两边被外壳盖着,在用的那几处一处都看不见
  it("表单:删一张存过的表单,确认框压在外壳之上、请画布让开,列出这个工作区里在用它的几处", async () => {
    const bridge = await mount();
    api.getCanvasApp.mockResolvedValue(appData({ app: { status: "ok", version: "2", upgradable: false, results: [], invalid: 0,
                                                        stray: 0, forms: [{ id: "k3x9a2", title: "调步数", description: "",
                                                                            fields: 1, invalid: 0, model: "古风.json#k3x9a2",
                                                                            tool: "wf_x_k3x9a2", items: [] }] } }));
    api.getFormUsages.mockResolvedValue({ uses: [{ kind: "board", id: "b1", name: "海报", count: 1 }] });
    tab("workbenchTabApp");
    fireEvent.click(await screen.findByRole("button", { name: "workflowFormActions" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "workflowFormDelete" }));
    const ask = await screen.findByRole("alertdialog");
    expect(ask.className, "压在外壳(z-200)之上").toMatch(/\bz-\[205\]/);
    await waitFor(() => expect(bridge.mosaelPublish.setOverlay).toHaveBeenLastCalledWith(true));
    await waitFor(() => expect(within(ask).getAllByRole("listitem")).toHaveLength(1));
    expect(api.getFormUsages).toHaveBeenCalledWith("i1", { workspace_id: "w1", model: "古风.json#k3x9a2", tool: "wf_x_k3x9a2" });
    fireEvent.click(within(ask).getByRole("button", { name: "cancel" }));
    await waitFor(() => expect(bridge.mosaelPublish.setOverlay).toHaveBeenLastCalledWith(false));
  });

  //: PLG-10:「表单」页签此前按 workflow.key 重挂,一张没存过的工作流第一次存盘(或改名、挪文件夹)时 key 变了,没同步的草稿静默没了
  it("表单:没同步到画布的草稿,在 ComfyUI 里第一次存盘 / 改名之后还在;换到别的一张才重读", async () => {
    const unsaved = { path: "", name: "Unsaved Workflow", temporary: true, modified: true, key: "Unsaved Workflow", revision: 1 };
    const saved = { path: "人像/新的.json", name: "新的", temporary: false, modified: false, key: "workflows/人像/新的.json",
                    revision: 2 };
    const bridge = await mount(state({ workflow: unsaved }));
    api.getCanvasApp.mockResolvedValue(appData());
    tab("workbenchTabApp");
    await waitFor(() => expect(document.querySelector("[data-no-forms]")).toBeTruthy());
    fireEvent.click(within(document.querySelector("[data-no-forms]") as HTMLElement).getByRole("button", { name: /workflowFormNew/ }));
    fireEvent.change(screen.getByPlaceholderText("workflowAppNamePlaceholder"), { target: { value: "草稿里的" } });
    expect(api.getCanvasApp).toHaveBeenCalledTimes(1);
    bridge.emit(state({ workflow: saved, renames: [{ from: unsaved, to: saved }] }));
    await waitFor(() => expect(screen.getByText("新的")).toBeTruthy());
    expect((screen.getByPlaceholderText("workflowAppNamePlaceholder") as HTMLInputElement).value, "草稿还在").toBe("草稿里的");
    expect(api.getCanvasApp, "同一张:不重读、不重挂").toHaveBeenCalledTimes(1);
    const renamed = { ...saved, path: "归档/新的.json", key: "workflows/归档/新的.json", revision: 3 };
    bridge.emit(state({ workflow: renamed, renames: [{ from: saved, to: renamed }] }));
    expect((screen.getByPlaceholderText("workflowAppNamePlaceholder") as HTMLInputElement).value, "再改名也还在").toBe("草稿里的");
    bridge.emit(state({ workflow: { ...GUFENG } }));
    await waitFor(() => expect(api.getCanvasApp).toHaveBeenCalledTimes(2));
  });

  /** 「表单」页签里新建一张、起好名字:草稿改过了,「同步到画布」点得了。 */
  async function draftAForm() {
    if (!screen.queryByRole("tab", { name: "workbenchTabApp", selected: true })) tab("workbenchTabApp");
    await waitFor(() => expect(document.querySelector("[data-no-forms]")).toBeTruthy());
    fireEvent.click(within(document.querySelector("[data-no-forms]") as HTMLElement).getByRole("button", { name: /workflowFormNew/ }));
    fireEvent.change(screen.getByPlaceholderText("workflowAppNamePlaceholder"), { target: { value: "调步数" } });
    return screen.findByRole("button", { name: /workbenchAppWrite/ });
  }

  //: PLG-17:导出 → 插件算标记 → 写进画布,此前写给「此刻」开着的那张;在 ComfyUI 里刚换到同一个模板改出来的另一张(节点号一样),
  //: 这张的表单就写进了那张
  it("表单:点「同步到画布」那一下画布上已经换了一张(面板还没跟上)—— 不拿这张的草稿去算那张,一处不写,说清楚", async () => {
    const bridge = await mount();
    api.getCanvasApp.mockResolvedValue(appData());
    const write = await draftAForm();
    bridge.comfyWorkbench.mockImplementation(async ({ call }: { call: ComfyWorkbenchCall }) =>
      call.op === "export" ? { ok: true, export: { ...EXPORTED, at: { key: "workflows/人像/古风 2.json", revision: 4 } } } : { ok: true });
    fireEvent.click(write);
    expect(await screen.findByText("workbenchCanvasSwitched")).toBeTruthy();
    expect(api.getCanvasMarks, "不拿这张的草稿去算那张").not.toHaveBeenCalled();
    expect(calls(bridge).some((one) => one.op === "setMarks")).toBe(false);
    expect((screen.getByPlaceholderText("workflowAppNamePlaceholder") as HTMLInputElement).value, "草稿还在").toBe("调步数");
  });

  it("表单:插件算标记的那一下这张又改过(桥回 changed)—— 按改过的那份重算一次再写;换了一张(桥回 otherWorkflow)—— 不重试、一处不写", async () => {
    const bridge = await mount();
    api.getCanvasApp.mockResolvedValue(appData());
    api.getCanvasMarks.mockResolvedValue({ nodes: {}, extra: { version: 2, forms: [] } });
    const write = await draftAForm();
    let revision = 1;
    const answers: { ok: boolean; error?: string }[] = [{ ok: false, error: "changed" }, { ok: true }];
    bridge.comfyWorkbench.mockImplementation(async ({ call }: { call: ComfyWorkbenchCall }) => {
      if (call.op === "export") return { ok: true, export: { ...EXPORTED, at: { key: GUFENG.key, revision: revision++ } } };
      if (call.op === "setMarks") return answers.shift() ?? { ok: true };
      return { ok: true };
    });
    fireEvent.click(write);
    expect(await screen.findByText("workbenchAppWritten")).toBeTruthy();
    const marked = calls(bridge).filter((one) => one.op === "setMarks");
    expect(marked.map((one) => (one as { expect: unknown }).expect), "第二次按重新导出的那份写")
      .toEqual([{ key: GUFENG.key, revision: 1 }, { key: GUFENG.key, revision: 2 }]);
    expect(api.getCanvasMarks, "按改过的那份重算").toHaveBeenCalledTimes(2);
    expect(api.getCanvasMarks.mock.calls[1][1].content).toEqual(EXPORTED.workflow);

    //: 写完重读(插件那边这里还是没有表单):再新建一张、再写,这回插件算的那一下换了一张
    answers.push({ ok: false, error: "otherWorkflow" });
    fireEvent.click(await draftAForm());
    expect(await screen.findByText("workbenchCanvasSwitched")).toBeTruthy();
    expect(calls(bridge).filter((one) => one.op === "setMarks"), "换了一张:不重试").toHaveLength(3);
  });

  //: PLG-1:上一版的表单这一版读成「没有表单」,此前照常摆编辑器、「结果取自」;写一次再一存盘,作者的表单就永久没了
  it("表单:画布上这张的表单是上一版的 —— 不摆编辑器、不给写,说清楚;「查看并升级」和工作流库同一个弹窗,压在外壳之上", async () => {
    const bridge = await mount(state({ workflow: { ...GUFENG, modified: false } }));
    api.getCanvasApp.mockResolvedValue(appData({ app: { status: "unsupported", version: "1", upgradable: true, forms: [],
                                                        results: [], invalid: 0, stray: 0 } }));
    api.getWorkflowLibrary.mockResolvedValue({
      workflows: [{ path: "人像/古风.json", label: "古风", modified: 12, app: { status: "unsupported", version: "1", upgradable: true } },
                  { path: "别的.json", label: "别的", modified: 3, app: { status: "ok", version: "2", upgradable: false } }],
      manager: { version: "V4.0" },
    });
    tab("workbenchTabApp");
    expect(await screen.findByText("workbenchFormsOld")).toBeTruthy();
    const panel = shownPanel();
    expect(within(panel).queryByRole("button", { name: /workbenchAppWrite/ }), "不给写进画布").toBeNull();
    expect(panel.querySelector("[data-no-forms]"), "不说「没有表单」、不给新建").toBeNull();
    expect(within(panel).queryByText(/workflowAppResults/), "不摆「结果取自」").toBeNull();
    fireEvent.click(within(panel).getByRole("button", { name: "workflowFormsUpgradeOpen" }));
    await waitFor(() => expect(api.getWorkflowLibrary).toHaveBeenCalledWith("i1", "w1"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.className, "压在外壳(z-200)之上").toMatch(/\bz-\[205\]/);
    await waitFor(() => expect(bridge.mosaelPublish.setOverlay).toHaveBeenLastCalledWith(true));
    expect(within(dialog).getByText("人像/古风.json")).toBeTruthy();
    expect(within(dialog).queryByText("别的.json"), "只列上一版的那几张").toBeNull();
    expect(api.getCanvasMarks, "什么都没往画布上写").not.toHaveBeenCalled();
    expect(calls(bridge).some((one) => one.op === "setMarks")).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "cancel" }));
    await waitFor(() => expect(bridge.mosaelPublish.setOverlay).toHaveBeenLastCalledWith(false));
  });

  it("表单:更新版插件写的表单 —— 说升级 Mosael,不给升级也不给写;画布上有没存的改动时上一版的也先不给升级", async () => {
    const bridge = await mount();
    api.getCanvasApp.mockResolvedValue(appData({ app: { status: "unsupported", version: "3", upgradable: false, forms: [],
                                                        results: [], invalid: 0, stray: 0 } }));
    tab("workbenchTabApp");
    expect(await screen.findByText("workbenchFormsNewer")).toBeTruthy();
    expect(within(shownPanel()).queryByRole("button", { name: "workflowFormsUpgradeOpen" })).toBeNull();
    expect(within(shownPanel()).queryByRole("button", { name: /workbenchAppWrite/ })).toBeNull();
    api.getCanvasApp.mockResolvedValue(appData({ app: { status: "unsupported", version: "1", upgradable: true, forms: [],
                                                        results: [], invalid: 0, stray: 0 } }));
    bridge.emit(state({ workflow: { ...GUFENG, modified: true, revision: 2 } }));
    fireEvent.click(within(shownPanel()).getByRole("button", { name: /workbenchAppReload/ }));
    const upgrade = await within(shownPanel()).findByRole("button", { name: "workflowFormsUpgradeOpen" });
    expect(upgrade.hasAttribute("disabled"), "升级完要重新打开这张:没存的改动会丢").toBe(true);
  });

  it("运行:这张的表单是上一版的 —— 「只要这个节点的图」不给点,说去「表单」页签升级;一个字都不往画布上写", async () => {
    const bridge = await mount();
    api.runCanvas.mockResolvedValue({ generation: { id: "g1", kind: "image" }, job: { id: "job-9", status: "queued" } });
    api.getJob.mockResolvedValue(SUCCEEDED);
    api.getCanvasApp.mockResolvedValue(appData({ app: { status: "unsupported", version: "1", upgradable: true, forms: [],
                                                        results: [], invalid: 0, stray: 0 } }));
    fireEvent.click(screen.getByRole("button", { name: /workbenchRun/ }));
    const preview = await screen.findByRole("region", { name: "PreviewImage #17" });
    expect(await screen.findByText("workbenchRunFormsOld")).toBeTruthy();
    expect(within(preview).queryByRole("button", { name: "workbenchRunOnlyThisLabel" })).toBeNull();
    //: 面板读完之前就点了(按钮还在的那一下):改标记那一步自己再看一眼,照样不写
    await expect(markOnlyResult("i1", GUFENG.key, "17")).rejects.toBeInstanceOf(FormsLockedError);
    expect(api.getCanvasMarks).not.toHaveBeenCalled();
    expect(calls(bridge).some((one) => one.op === "setMarks")).toBe(false);
  });

  it("运行:跑画布上这张(API 图、界面格式、前端的 clientId);产出按来自的节点分组、标节点名;「只要这个节点的图」标在画布上", async () => {
    const bridge = await mount();
    api.runCanvas.mockResolvedValue({ generation: { id: "g1", kind: "image" }, job: { id: "job-9", status: "queued" } });
    api.getJob.mockResolvedValue(SUCCEEDED);
    api.getCanvasApp.mockResolvedValue(appData({ app: { status: "ok", version: "1", upgradable: false, forms: [],
                                                        results: ["9"], invalid: 0, stray: 0 } }));
    api.getCanvasMarks.mockResolvedValue({ nodes: { "17": { result: true } }, extra: { version: 1 } });
    fireEvent.click(screen.getByRole("button", { name: /workbenchRun/ }));
    await waitFor(() => expect(api.runCanvas).toHaveBeenCalledWith("i1", {
      workspace_id: "w1", path: "人像/古风.json", prompt: EXPORTED.prompt, workflow: EXPORTED.workflow, client_id: EXPORTED.clientId,
    }));
    const preview = await screen.findByRole("region", { name: "PreviewImage #17" });
    expect(within(preview).getAllByRole("img")[0].getAttribute("src")).toBe("thumb://a1");
    expect(screen.getByRole("region", { name: "高清 #9" })).toBeTruthy();
    fireEvent.click(await within(preview).findByRole("button", { name: "workbenchRunOnlyThisLabel" }));
    await waitFor(() => expect(api.getCanvasMarks).toHaveBeenCalled());
    expect(api.getCanvasMarks.mock.calls[0][1].results, "只标这一个,清掉别的").toEqual(["17"]);
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "setMarks", marks: { nodes: { "17": { result: true } }, extra: { version: 1 } },
                                                                expect: EXPORTED.at }));
    expect(await screen.findByText("workbenchRunMarked")).toBeTruthy();
  });

  it("运行:和在 ComfyUI 里点「运行」一样,导出之前、任务建好之后各让桥走一遍「生成后怎样」;没建成的不走第二遍", async () => {
    //: 沙盒实测:种子设成 randomize,连点两次运行此前用的是同一个存着的种子,出同一张图
    const bridge = await mount();
    api.runCanvas.mockResolvedValue({ generation: { id: "g1", kind: "image" }, job: { id: "job-9", status: "queued" } });
    api.getJob.mockResolvedValue({ id: "job-9", status: "running", message: "ComfyUI 生成中" });
    fireEvent.click(screen.getByRole("button", { name: /workbenchRun/ }));
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "runControls", phase: "after" }));
    const ops = calls(bridge).map((one) => (one.op === "runControls" ? `runControls:${one.phase}` : one.op));
    const before = ops.indexOf("runControls:before");
    const after = ops.indexOf("runControls:after");
    expect(before, "先走一遍再导出").toBeGreaterThanOrEqual(0);
    expect(ops.indexOf("export", before)).toBeGreaterThan(before);
    expect(ops.indexOf("export", before)).toBeLessThan(after);
    expect(ops.filter((op) => op.startsWith("runControls"))).toEqual(["runControls:before", "runControls:after"]);
    expect(api.runCanvas.mock.invocationCallOrder[0], "任务建好了才换种子")
      .toBeLessThan(bridge.comfyWorkbench.mock.invocationCallOrder[calls(bridge).findIndex((one) => one.op === "runControls" &&
                                                                       one.phase === "after")]);

    bridge.comfyWorkbench.mockClear();
    api.runCanvas.mockRejectedValue(Object.assign(new Error("ComfyUI 拒绝了"), { status: 500 }));
    fireEvent.click(screen.getByRole("button", { name: "workbenchRun" }));
    await waitFor(() => expect(api.runCanvas).toHaveBeenCalledTimes(2));
    await act(async () => undefined);
    expect(calls(bridge).filter((one) => one.op === "runControls"), "没排上:种子不换(ComfyUI 自己也是)")
      .toEqual([{ op: "runControls", phase: "before" }]);
  });

  it("运行:刚存的那张宿主的目录还没刷新到(422)就刷新一次再试", async () => {
    await mount();
    api.runCanvas.mockRejectedValueOnce(Object.assign(new Error("还不是生成模型"), { status: 422 }))
      .mockResolvedValueOnce({ generation: { id: "g1", kind: "image" }, job: { id: "job-9", status: "queued" } });
    api.refreshPluginInstance.mockResolvedValue({});
    api.getJob.mockResolvedValue({ id: "job-9", status: "running", message: "ComfyUI 生成中" });
    fireEvent.click(screen.getByRole("button", { name: /workbenchRun/ }));
    await waitFor(() => expect(api.runCanvas).toHaveBeenCalledTimes(2));
    expect(api.refreshPluginInstance).toHaveBeenCalledWith("i1");
    expect(await screen.findByText("ComfyUI 生成中")).toBeTruthy();
  });

  it("这版前端缺了哪一样,那一处说「不支持」,别的照常", async () => {
    await mount(state({ capabilities: { ...CAPS, export: false, save: false } }));
    expect(screen.getByRole("button", { name: /workbenchSave/ }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: /workbenchRun/ }).hasAttribute("disabled")).toBe(true);
    tab("workbenchTabMissing");
    expect(within(column()).getByText("workbenchUnsupported")).toBeTruthy();
    tab("workbenchTabModels");
    expect(await within(column()).findByRole("list", { name: "workbenchModelsList" }), "选中、填值还在:模型库照常").toBeTruthy();
  });
});

describe("版式:空的、在读的摆在面板正中;每个页签自己滚动;顶栏的控件一样大", () => {
  /** 摆在正中:这一块占满剩下的高(flex-1)、内容上下左右居中;它的上一层是竖排的 flex(页签或面板的根)。 */
  const centered = (element: HTMLElement) => {
    expect(element.className).toMatch(/\bflex-1\b/);
    const inner = element.matches("[data-panel-state]") ? element : element.firstElementChild as HTMLElement;
    if (element.matches("[data-panel-state]")) {
      expect(inner.className).toMatch(/\bitems-center\b/);
      expect(inner.className).toMatch(/\bjustify-center\b/);
    } else {
      expect(inner.className, "LoadingState 里那一层靠 m-auto 居中").toMatch(/\bm-auto\b/);
    }
    for (let parent = element.parentElement; parent && parent !== column(); parent = parent.parentElement) {
      expect(parent.className, "一路往上都是竖排、占满的 flex").toMatch(/\bflex-col\b/);
      expect(parent.className).toMatch(/\bflex-1\b/);
    }
  };

  it("连上之前转圈在正中;模型库没选节点、缺失项什么都不缺、运行与结果还没跑过:一句话在正中", async () => {
    const bridge = await mount(null);
    centered(within(column()).getByRole("status"));
    bridge.emit(state({ selection: { count: 0, node: null } }));
    centered(within(column()).getByText("workbenchModelsPick").closest<HTMLElement>("[data-panel-state]")!);
    tab("workbenchTabMissing");
    centered((await within(column()).findByText("workbenchMissingNone")).closest<HTMLElement>("[data-panel-state]")!);
    tab("workbenchTabRun");
    centered(within(column()).getByText("workbenchRunEmpty").closest<HTMLElement>("[data-panel-state]")!);
  });

  it("在读模型、在检查画布的转圈也在正中", async () => {
    api.getNodeFolders.mockReturnValue(new Promise(() => undefined));
    api.inspectWorkflowImport.mockReturnValue(new Promise(() => undefined));
    await mount();
    centered(within(shownPanel()).getByRole("status"));
    tab("workbenchTabMissing");
    centered(await within(shownPanel()).findByRole("status"));
  });

  it("每个页签是它自己的滚动层,拿得到焦点(键盘滚动、内嵌网页亮着时按键不被吞)", async () => {
    await mount();
    for (const name of ["workbenchTabMissing", "workbenchTabApp", "workbenchTabRun", "workbenchTabModels"]) {
      tab(name);
      const panel = shownPanel();
      expect(panel.className).toMatch(/\boverflow-y-auto\b/);
      expect(panel.className).toMatch(/\bmin-h-0\b/);
      expect(panel.tabIndex).toBe(0);
      expect(panel.closest("[data-app-chrome]"), "落在外壳里(embeddedFocus 不吞外壳里的按键)").not.toBeNull();
    }
  });

  it("顶栏的控件一样大:返回、操控方式、保存、运行、收起面板都是 sm 那一档(32px、同一个字号),排在栏的正中", async () => {
    await mount();
    const bar = document.querySelector<HTMLElement>("[data-comfy-workbench-bar]")!;
    expect(bar.className).toMatch(/\bitems-center\b/);
    const controls = [...bar.querySelectorAll<HTMLElement>("[data-bar-control]")];
    expect(controls.map((one) => one.getAttribute("aria-label") || one.textContent)).toEqual([
      "publishBackToApp", "workbenchSave", "workbenchRun", "workbenchColumnHide",
    ]);
    for (const one of controls) {
      expect(one.className, `${one.textContent}:32px 高`).toMatch(/\b(h-8|size-8)\b/);
      expect(one.className, `${one.textContent}:同一个字号`).toMatch(/\btext-ui-sm\b/);
    }
    expect(bar.querySelector("[data-publish-back]")!.className, "返回不再手写自己的内边距和字号").not.toMatch(/py-\[5px\]/);
    const crumbs = bar.querySelector<HTMLElement>("h1")!.parentElement!;
    expect(crumbs.className).toMatch(/\bitems-center\b/);
    expect(crumbs.className).toMatch(/\btext-ui-sm\b/);
    const toggle = bar.querySelector<HTMLElement>("[data-canvas-input-trigger]")!;
    expect(toggle.className, "操控方式:和别的按钮一样高(一颗小图标按钮,不再是一大段分段控件)").toMatch(/\bh-8\b/);
  });
});

describe("右边那一列拉宽拉窄", () => {
  const handle = () => screen.getByRole("separator", { name: "workbenchColumnResize" });
  const width = () => Number.parseInt(column().style.width, 10);
  const drag = (from: number, to: number) => {
    fireEvent.pointerDown(handle(), { clientX: from, button: 0, buttons: 1, pointerId: 1 });
    fireEvent.pointerMove(window, { clientX: to, buttons: 1, pointerId: 1 });
  };

  it("拖左边沿:往左变宽、往右变窄,夹在 300 和窗口的一半之间;拖着时网页多让出一截,松手按列宽让", async () => {
    window.innerWidth = 1440;
    const bridge = await mount();
    expect(width()).toBe(COLUMN_DEFAULT);
    expect(handle().getAttribute("aria-valuenow")).toBe(String(COLUMN_DEFAULT));
    expect(handle().getAttribute("aria-valuemin")).toBe(String(COLUMN_MIN));
    expect(handle().getAttribute("aria-valuemax")).toBe("720");
    drag(1000, 900);
    expect(width()).toBe(COLUMN_DEFAULT + 100);
    const guard = document.querySelector<HTMLElement>("[data-workbench-drag-guard]");
    expect(guard, "让出来的那一截铺一块底色").not.toBeNull();
    //: 它要读作「那一列自己的延伸」(和 aside 同色、带分割线),不是画布旁边一条颜色对不上的空白。
    expect(guard!.className).toContain("bg-panel");
    expect(guard!.className).toContain("border-l");
    await waitFor(() => expect(bridge.mosaelPageTools.setInset).toHaveBeenLastCalledWith(COLUMN_DEFAULT + 100 + DRAG_GUARD));
    fireEvent.pointerMove(window, { clientX: 100, buttons: 1, pointerId: 1 });
    expect(width(), "最宽是窗口的一半(主进程也最多让出一半)").toBe(720);
    fireEvent.pointerMove(window, { clientX: 1400, buttons: 1, pointerId: 1 });
    expect(width(), "最窄 300").toBe(COLUMN_MIN);
    fireEvent.pointerUp(window, { pointerId: 1 });
    expect(document.querySelector("[data-workbench-drag-guard]")).toBeNull();
    await waitFor(() => expect(bridge.mosaelPageTools.setInset).toHaveBeenLastCalledWith(COLUMN_MIN));
  });

  it("拖柄的竖条压在列左边那条分割线上、和别处一样;热区不往线左边(原生的画布底下)伸", async () => {
    //: 维护者:「这个拖动边界手柄为何有间距了,和其他的手柄设计语言不一致」—— 热区从列的边线之后起、竖条居中,离线 4px
    await mount();
    const classes = handle().className.split(/\s+/);
    expect(classes, "外观是全应用那一份").toEqual(expect.arrayContaining(HANDLE_COLUMN.split(" ")));
    expect(classes, "从列自己那条 1px 边线上起、竖条靠左贴着线").toEqual(expect.arrayContaining(HANDLE_ON_LEFT_EDGE.split(" ")));
    expect(classes, "不再从边线之后起").not.toContain("left-0");
    expect(column().className).toMatch(/\bborder-l\b/);
  });

  it("松手落在原生视图上(渲染层没收到 pointerup):回来第一下没按着键就当松手;窗口失焦也收住", async () => {
    window.innerWidth = 1440;
    await mount();
    drag(1000, 950);
    fireEvent.pointerMove(window, { clientX: 700, buttons: 0, pointerId: 1 });
    expect(width(), "没按着键:不再跟着指针").toBe(COLUMN_DEFAULT + 50);
    expect(document.querySelector("[data-workbench-drag-guard]")).toBeNull();
    drag(1000, 990);
    fireEvent.blur(window);
    fireEvent.pointerMove(window, { clientX: 500, buttons: 1, pointerId: 1 });
    expect(width()).toBe(COLUMN_DEFAULT + 60);
  });

  it("方向键一下 16(Shift 四倍),Home / End 到最窄 / 最宽,双击回到默认宽;记在本机,下次打开还是这个宽", async () => {
    window.innerWidth = 1440;
    const bridge = await mount();
    fireEvent.keyDown(handle(), { key: "ArrowLeft" });
    expect(width()).toBe(COLUMN_DEFAULT + 16);
    fireEvent.keyDown(handle(), { key: "ArrowRight", shiftKey: true });
    expect(width()).toBe(COLUMN_DEFAULT + 16 - 64);
    fireEvent.keyDown(handle(), { key: "End" });
    expect(width()).toBe(720);
    fireEvent.keyDown(handle(), { key: "Home" });
    expect(width()).toBe(COLUMN_MIN);
    await waitFor(() => expect(bridge.mosaelPageTools.setInset).toHaveBeenLastCalledWith(COLUMN_MIN));
    fireEvent.doubleClick(handle());
    expect(width()).toBe(COLUMN_DEFAULT);
    fireEvent.keyDown(handle(), { key: "ArrowLeft" });
    bridge.view.unmount();
    resetWorkbench();
    await mount();
    expect(width(), "下次打开还是这个宽").toBe(COLUMN_DEFAULT + 16);
  });
});

describe("底下开着模态弹窗(工作流库)时:那一列滚得动、小眼睛弹得出来;回来时模糊还在弹窗后面", () => {
  // 真机上:从工作流库「在工作台里打开」,工作流库留在底下(回来时还在那一张)。它是模态的:遮罩带着 react-remove-scroll,在
  // document 上拦下弹窗外面的 wheel;焦点圈套把跑到外面的焦点拽回来。那一列是外壳(APP_CHROME),两样都不该碰到它 ——
  // App 装着 installAppChromeGuards,这里也装上。
  let uninstall = () => undefined as void;
  beforeEach(() => {
    uninstall = installAppChromeGuards(document);
  });
  afterEach(() => uninstall());

  const library = async () => {
    const { Dialog, DialogContent, DialogTitle } = await import("@/components/ui/dialog");
    return (
      <Dialog open>
        <DialogContent>
          <DialogTitle>工作流库</DialogTitle>
        </DialogContent>
      </Dialog>
    );
  };
  const wheel = (target: HTMLElement) => {
    const event = new WheelEvent("wheel", { deltaY: 120, bubbles: true, cancelable: true });
    target.dispatchEvent(event);
    return event.defaultPrevented;
  };
  const libraryDialog = () => screen.getByRole("dialog", { name: "工作流库", hidden: true });

  it("顶栏拖得动窗口:排在底下工作流库的遮罩和内容(都声明 no-drag)后面", async () => {
    // 拖拽区按文档顺序合、后面的盖前面的(见 test/dragRegions)。顶栏留在应用的根节点里,就排在工作流库那两个 portal 前面,
    // 被整窗的遮罩减掉 —— 真机上就是拖不动。所以先让工作流库开着(真机上就是从它里面点的),再在同一棵树里挂上工作台。
    const bridge = desktop();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const dialog = await library();
    const tree = (workbench: boolean) => (
      <QueryClientProvider client={client}>
        <ImagePreviewProvider>
          {dialog}
          {workbench && <ComfyWorkbench barHeight={56} />}
        </ImagePreviewProvider>
      </QueryClientProvider>
    );
    const view = render(tree(false));
    await waitFor(() => expect(document.querySelector(".modal-overlay")).not.toBeNull());
    await openWorkbench(TARGET, { path: "人像/古风.json" });
    view.rerender(tree(true));
    bridge.emit(state());
    const bar = document.querySelector("[data-comfy-workbench-bar]")!;
    expect(declaresDrag(bar), "顶栏是拖拽区").toBe(true);
    expect(noDragAfter(bar), "没有排在顶栏后面的 no-drag").toEqual([]);
    expect(libraryDialog(), "工作流库还开着").toBeTruthy();
  });

  it("滚轮在那一列里不被拦下;弹窗外面的别处照样被它的滚动锁拦着", async () => {
    const bridge = await mount(state(), await library());
    bridge.viewUp(true);
    expect(wheel(shownPanel()), "那一列滚得动").toBe(false);
    expect(wheel(document.body), "滚动锁还在(只是不管外壳)").toBe(true);
    expect(document.body.hasAttribute("data-scroll-locked")).toBe(true);
  });

  it("视图亮了又收起(「返回 Mosael」):遮罩一直是那一个,排在弹窗内容前面 —— 模糊不盖住弹窗", async () => {
    const bridge = await mount(state(), await library());
    const overlay = document.querySelector(".modal-overlay");
    expect(overlay).not.toBeNull();
    bridge.viewUp(true);
    bridge.viewUp(false);
    const now = document.querySelector(".modal-overlay")!;
    expect(now.compareDocumentPosition(libraryDialog()) & Node.DOCUMENT_POSITION_FOLLOWING, "遮罩在内容前面").toBeTruthy();
    expect(now, "没有卸掉再挂回来(挂回来会追加到 body 末尾)").toBe(overlay);
  });

  it("模型库的小眼睛:弹得出来、抬在那一列之上;焦点进得去,不被弹窗拽回去关掉;底下的工作流库还在", async () => {
    const bridge = await mount(state(), await library());
    bridge.viewUp(true);
    fireEvent.click(await within(column()).findByRole("button", { name: "modelPreviewSettings" }));
    const settings = await screen.findByRole("dialog", { name: "modelPreviewSettings", hidden: true });
    expect(settings.hasAttribute("data-over-chrome"), "抬到 z 200 的那一列之上").toBe(true);
    expect(settings.hasAttribute("data-app-chrome"), "也算外壳").toBe(true);
    await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
    expect(settings.isConnected, "没被当成焦点跑到外面关掉").toBe(true);
    expect(settings.contains(document.activeElement), "焦点在设置里").toBe(true);
    const show = within(settings).getByRole("radio", { name: "modelPreviewNsfwShow", hidden: true });
    fireEvent.click(show);
    expect(show.getAttribute("aria-checked")).toBe("true");
    expect(libraryDialog()).toBeTruthy();
  });
});

describe("模型库:每一行的第二行不重复第一行", () => {
  //: 沙盒实测:没有标题、没有触发词的模型,第一行是文件名,第二行又是一遍文件名
  it("有触发词写触发词;有标题写文件名;都没有就写子目录,再没有就不写", async () => {
    api.getModelLibrary.mockResolvedValue({
      folders: [], missing: [], downloads: [], download: { route: "local", note: "" },
      models: [
        { folder: "checkpoints", name: "sdxl.safetensors", family: "SDXL", title: "SDXL Base", triggers: [], has_preview: false },
        { folder: "checkpoints", name: "flux-dev.safetensors", family: "", title: "", triggers: ["film grain"], has_preview: false },
        { folder: "checkpoints", name: "plain.safetensors", family: "SD 1.5", title: "", triggers: [], has_preview: false },
        { folder: "checkpoints", name: "Qwen_Image/qwen.safetensors", family: "", title: "", triggers: [], has_preview: false },
      ],
    });
    await mount();
    const list = await screen.findByRole("list", { name: "workbenchModelsList" });
    const row = (name: RegExp) => within(list).getByRole("button", { name }).textContent;
    expect(row(/SDXL Base/)).toContain("sdxl.safetensors");
    expect(row(/flux-dev/)).toContain("film grain");
    expect(row(/plain\.safetensors/)!.split("plain.safetensors")).toHaveLength(2);
    expect(row(/qwen\.safetensors/)).toContain("Qwen_Image");
    expect(row(/qwen\.safetensors/)!.split("qwen.safetensors")).toHaveLength(2);
  });
});

describe("模型库:换模型不闪;点缩略图看大图", () => {
  it("点一行:没填成的那一句一直留着、回话到了才换;填成了不另说一句、那一句撤掉;列表里的每一行不重挂", async () => {
    const bridge = await mount();
    const list = await screen.findByRole("list", { name: "workbenchModelsList" });
    fireEvent.click(within(list).getByRole("button", { name: /film grain/ }));
    await waitFor(() => expect(calls(bridge)).toContainEqual(expect.objectContaining({ op: "setWidget", value: "flux-dev.safetensors" })));
    expect(within(column()).queryByRole("status"), "填成了不另说一句").toBeNull();
    bridge.comfyWorkbench.mockImplementationOnce(async () => ({ ok: false, error: "notInList" }));
    fireEvent.click(within(list).getByRole("button", { name: /SDXL Base/ }));
    const note = await within(column()).findByText(/workbenchModelsNotInList/);
    const rows = within(list).getAllByRole("listitem");
    let answer: (value: unknown) => void = () => undefined;
    bridge.comfyWorkbench.mockImplementationOnce(() => new Promise((resolve) => (answer = resolve)) as never);
    fireEvent.click(within(list).getByRole("button", { name: /Pony/ }));
    await waitFor(() => expect(calls(bridge)).toContainEqual(expect.objectContaining({ op: "setWidget", value: "pony.safetensors" })));
    expect(note.isConnected, "填的过程中那一句不撤掉(撤掉再放回来,整个列表上下跳一下)").toBe(true);
    expect(within(list).getByRole("button", { name: /Pony/ }).getAttribute("aria-busy"), "点的那一行在转圈").toBe("true");
    await act(async () => answer({ ok: true, value: "pony.safetensors" }));
    expect(note.isConnected, "填成了:上一次没填成的那句撤掉").toBe(false);
    expect(within(list).getAllByRole("listitem").every((row, index) => row === rows[index]), "每一行都是原来那个元素").toBe(true);
  });

  it("点缩略图打开大图(这一页有预览图的成组翻、标题是模型名),不填进画布;Esc 关掉、焦点回到缩略图;没有预览图的没有这个按钮", async () => {
    const bridge = await mount();
    const list = await screen.findByRole("list", { name: "workbenchModelsList" });
    expect(within(list).getAllByRole("button", { name: /workbenchModelsPreview/ }), "只有有预览图的那两个").toHaveLength(2);
    const flux = within(list).getAllByRole("listitem")[0];
    expect(within(flux).queryByRole("button", { name: /workbenchModelsPreview/ })).toBeNull();
    const thumb = within(list).getAllByRole("button", { name: /workbenchModelsPreview/ })[0];
    thumb.focus();
    fireEvent.click(thumb);
    const viewer = await waitFor(() => {
      const element = document.querySelector<HTMLElement>(".PhotoView-Portal");
      expect(element).not.toBeNull();
      return element!;
    });
    expect(viewer.textContent).toContain("Pony");
    expect(calls(bridge).some((one) => one.op === "setWidget"), "看大图不填").toBe(false);
    await waitFor(() => expect(bridge.mosaelPublish.setOverlay).toHaveBeenLastCalledWith(true));
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(bridge.mosaelPublish.setOverlay).toHaveBeenLastCalledWith(false));
    await waitFor(() => expect(document.activeElement).toBe(thumb));
  });
});

describe("运行与结果:节点名和应用表单、「结果取自」同一种叫法", () => {
  //: 沙盒实测:面板上写「PreviewImage #12」,表单和「结果取自」写「预览图像」—— 同一个节点两种叫法
  it("产出那一组、「现在取自」都用插件报的名字(预览图像),不是类名", async () => {
    await mount();
    api.runCanvas.mockResolvedValue({ generation: { id: "g1", kind: "image" }, job: { id: "job-9", status: "queued" } });
    api.getJob.mockResolvedValue(SUCCEEDED);
    api.getCanvasApp.mockResolvedValue(appData({
      outputs: [{ node: "9", title: "高清", label: "高清", class_type: "SaveImage", media: "image" },
                { node: "17", title: "PreviewImage", label: "预览图像", class_type: "PreviewImage", media: "image" }],
      names: { "4": "Checkpoint 加载器", "9": "高清", "17": "预览图像" },
      app: { status: "ok", version: "1", upgradable: false, forms: [], results: ["17"], invalid: 0, stray: 0 },
    }));
    fireEvent.click(screen.getByRole("button", { name: /workbenchRun/ }));
    expect(await screen.findByRole("region", { name: "预览图像 #17" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "PreviewImage #17" })).toBeNull();
    await waitFor(() => expect(document.querySelector("[data-results-from]")?.textContent).toContain("预览图像 #17"));
  });
});

describe("运行与结果:点结果看大图;结果取自哪个节点", () => {
  it("点一张结果:这一次的全部产出成组翻(按面板上的顺序),标题带来源节点和第几张", async () => {
    const bridge = await mount();
    api.runCanvas.mockResolvedValue({ generation: { id: "g1", kind: "image" }, job: { id: "job-9", status: "queued" } });
    api.getJob.mockResolvedValue(SUCCEEDED);
    api.getCanvasApp.mockResolvedValue(appData());
    fireEvent.click(screen.getByRole("button", { name: /workbenchRun/ }));
    const preview = await screen.findByRole("region", { name: "PreviewImage #17" });
    const buttons = within(preview).getAllByRole("button", { name: /workbenchPreviewOpen/ });
    fireEvent.click(buttons[1]);
    const viewer = await waitFor(() => {
      const element = document.querySelector<HTMLElement>(".PhotoView-Portal");
      expect(element).not.toBeNull();
      return element!;
    });
    // 面板上先是 PreviewImage #17 那一组(a1、a3),再是高清 #9(a2):点的是第一组的第二张
    await waitFor(() => expect(viewer.textContent).toContain("PreviewImage #17 · 2/3"));
    expect(viewer.textContent, "计数是这一次全部的三张").toMatch(/2\s*\/\s*3/);
    await waitFor(() => expect(bridge.mosaelPublish.setOverlay).toHaveBeenLastCalledWith(true));
  });

  it("标着的那一组写「结果取自这个节点」和「撤销」,别的组是「只要这个节点的图」;上面说清楚现在取自哪几个;撤销走同一条路", async () => {
    const bridge = await mount();
    api.runCanvas.mockResolvedValue({ generation: { id: "g1", kind: "image" }, job: { id: "job-9", status: "queued" } });
    api.getJob.mockResolvedValue(SUCCEEDED);
    const marked = (results: string[]) => appData({ app: { status: "ok", version: "2", upgradable: false, forms: [],
                                                            results, invalid: 0, stray: 0 } });
    api.getCanvasApp.mockResolvedValue(marked(["9", "5"]));
    api.getCanvasMarks.mockResolvedValue({ nodes: {}, extra: { version: 1 } });
    fireEvent.click(screen.getByRole("button", { name: /workbenchRun/ }));
    const saved = await screen.findByRole("region", { name: "高清 #9" });
    expect(await within(saved).findByText("workbenchRunIsResult")).toBeTruthy();
    expect(within(saved).queryByRole("button", { name: "workbenchRunOnlyThisLabel" }), "已经标着的不再给这个按钮").toBeNull();
    const preview = screen.getByRole("region", { name: "PreviewImage #17" });
    expect(within(preview).getByRole("button", { name: "workbenchRunOnlyThisLabel" })).toBeTruthy();
    expect(within(preview).queryByText("workbenchRunIsResult")).toBeNull();
    expect(document.querySelector("[data-results-from]")!.textContent, "两个都标着:都说出来").toContain("workbenchRunResultsFrom");
    fireEvent.click(within(saved).getByRole("button", { name: "workbenchRunUndoMarkLabel" }));
    await waitFor(() => expect(api.getCanvasMarks).toHaveBeenCalled());
    expect(api.getCanvasMarks.mock.calls[0][1].results, "撤销:只去掉这一个").toEqual(["5"]);
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "setMarks", marks: { nodes: {}, extra: { version: 1 } },
                                                                expect: EXPORTED.at }));
    expect(await screen.findByText("workbenchRunUnmarked")).toBeTruthy();
    expect(await within(saved).findByRole("button", { name: "workbenchRunOnlyThisLabel" }), "撤销之后又是那个按钮").toBeTruthy();
    bridge.emit(state({ workflow: { ...GUFENG, key: "workflows/别的.json", name: "别的", path: "别的.json" } }));
    expect(screen.queryByText("workbenchRunUnmarked"), "换了一张:上一张的那句话不带过来").toBeNull();
  });
});

describe("画布上换了一张工作流:右边那一列跟着换", () => {
  const OTHER = { path: "视频/i2v.json", name: "i2v", temporary: false, modified: false, key: "workflows/视频/i2v.json", revision: 1 };

  it("模型库、缺失项、应用各自重挂、从头读这一张;运行与结果先列这一张的,换走之前跑的收进「其他工作流」", async () => {
    const bridge = await mount();
    api.getCanvasApp.mockResolvedValue(appData());
    api.runCanvas.mockResolvedValue({ generation: { id: "g1", kind: "image" }, job: { id: "job-9", status: "queued" } });
    api.getJob.mockResolvedValue(SUCCEEDED);
    const list = await screen.findByRole("list", { name: "workbenchModelsList" });
    fireEvent.change(within(column()).getByRole("textbox", { name: "workbenchModelsSearch" }), { target: { value: "pony" } });
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    tab("workbenchTabMissing");
    await waitFor(() => expect(api.inspectWorkflowImport).toHaveBeenCalledTimes(1));
    tab("workbenchTabApp");
    await waitFor(() => expect(api.getCanvasApp).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: /workbenchRun/ }));
    await screen.findByRole("region", { name: "PreviewImage #17" });

    const appReads = api.getCanvasApp.mock.calls.length;
    bridge.emit(state({ workflow: { ...OTHER } }));
    expect(within(document.querySelector<HTMLElement>("[data-comfy-workbench-bar]")!).getByRole("heading").textContent).toBe("i2v");
    expect(screen.queryByRole("img", { name: "workbenchUnsavedChanges" }), "没存的改动跟着这一张").toBeNull();
    expect(within(column()).getByRole("tabpanel").textContent, "运行与结果:这一张还没跑过").toContain("workbenchRunEmptyHere");
    const others = within(column()).getByRole("button", { name: /workbenchRunOthersToggle/ });
    fireEvent.click(others);
    expect(within(column()).getByRole("region", { name: "古风" }), "之前那张跑的还看得到").toBeTruthy();
    tab("workbenchTabMissing");
    await waitFor(() => expect(api.inspectWorkflowImport, "缺失项自己重新检查这一张").toHaveBeenCalledTimes(2));
    tab("workbenchTabApp");
    await waitFor(() => expect(api.getCanvasApp, "应用重新读这一张").toHaveBeenCalledTimes(appReads + 1));
    tab("workbenchTabModels");
    expect((within(column()).getByRole("textbox", { name: "workbenchModelsSearch" }) as HTMLInputElement).value,
           "模型库从头来:上一张的搜索不带过来").toBe("");
  });

  it("没存过的几张(路径是空的)按前端里的那一张认:来回切也各是各的;不能跑,说先存一次", async () => {
    const unsaved = (n: number) => ({ path: "", name: `Unsaved Workflow (${n})`, temporary: true, modified: true,
                                      key: `workflows/Unsaved Workflow (${n}).json`, revision: 1 });
    const bridge = await mount(state({ workflow: unsaved(2) }));
    tab("workbenchTabMissing");
    await waitFor(() => expect(api.inspectWorkflowImport).toHaveBeenCalledTimes(1));
    bridge.emit(state({ workflow: unsaved(3) }));
    await waitFor(() => expect(api.inspectWorkflowImport).toHaveBeenCalledTimes(2));
    expect(within(document.querySelector<HTMLElement>("[data-comfy-workbench-bar]")!).getByRole("heading").textContent)
      .toBe("Unsaved Workflow (3)");
    expect(screen.getByRole("button", { name: /workbenchRun/ }).hasAttribute("disabled")).toBe(true);
    bridge.emit(state({ workflow: unsaved(3), selection: { count: 0, node: null } }));
    expect(api.inspectWorkflowImport, "同一张里只是换了选中:不重查").toHaveBeenCalledTimes(2);
  });

  it("同一张里改了图:最后一下改动之后过一会儿缺失项自己重新检查;「重新检查」照样在", async () => {
    const bridge = await mount();
    tab("workbenchTabMissing");
    await waitFor(() => expect(api.inspectWorkflowImport).toHaveBeenCalledTimes(1));
    // 真的等(react-query 的通知也走 setTimeout,假时钟会把它一起扣下)
    const sleep = (ms: number) => act(() => new Promise((resolve) => setTimeout(resolve, ms)));
    bridge.emit(state({ workflow: { ...GUFENG, revision: 2 } }));
    await sleep(RECHECK_DELAY_MS / 2);
    bridge.emit(state({ workflow: { ...GUFENG, revision: 3 } }));
    await sleep(RECHECK_DELAY_MS - 200);
    expect(api.inspectWorkflowImport, "最后一下改动之后还没过那么久:先不查").toHaveBeenCalledTimes(1);
    await waitFor(() => expect(api.inspectWorkflowImport, "停下来之后查一次(连着两下改动只查一次)").toHaveBeenCalledTimes(2),
                  { timeout: 2000 });
    await sleep(RECHECK_DELAY_MS);
    expect(api.inspectWorkflowImport).toHaveBeenCalledTimes(2);
    const recheck = within(column()).getByRole("button", { name: /workbenchMissingCheck/ });
    await waitFor(() => expect(recheck.hasAttribute("disabled")).toBe(false));
    fireEvent.click(recheck);
    await waitFor(() => expect(api.inspectWorkflowImport).toHaveBeenCalledTimes(3));
  });
});

describe("缺失项:定位到节点;按节点包装;找下载地址", () => {
  const SUB = "8f1c0e2a-9b7d-4c51";
  const WITH_SUBGRAPH = {
    ...EXPORTED,
    workflow: {
      nodes: [{ id: 4, type: "CheckpointLoaderSimple", widgets_values: ["wan/i2v-high.safetensors"] },
              { id: 7, type: "CR Prompt Text" }, { id: 8, type: "CR Prompt Text" }, { id: 11, type: "CR Image Size" },
              { id: 12, type: SUB }],
      definitions: { subgraphs: [{ id: SUB, name: "细节", nodes: [{ id: 5, type: "CheckpointLoaderSimple", widgets_values: ["i2v-high.safetensors"] }] }] },
    },
  };
  const missing = {
    missing_nodes: [
      { type: "CR Prompt Text", count: 2, packs: [{ id: "comfyroll", title: "Comfyroll", installed: false }] },
      { type: "CR Image Size", count: 1, packs: [{ id: "comfyroll", title: "Comfyroll", installed: false }] },
    ],
    missing_models: [{ folder: "checkpoints", name: "wan/i2v-high.safetensors", url: "" }],
  };

  async function missingTab() {
    const bridge = await mount();
    bridge.comfyWorkbench.mockImplementation(async ({ call }: { call: ComfyWorkbenchCall }) => {
      if (call.op === "export") return { ok: true, export: WITH_SUBGRAPH };
      if (call.op === "locate" && call.subgraph) return { ok: false, error: "inSubgraph" };
      return { ok: true };
    });
    api.inspectWorkflowImport.mockResolvedValue(missing);
    tab("workbenchTabMissing");
    await within(column()).findByText("CR Prompt Text");
    return bridge;
  }

  it("同一个包里缺的几种节点一组、一个「安装」;每一种都能定位,好几处的点一下换下一处", async () => {
    const bridge = await missingTab();
    const groups = column().querySelectorAll("[data-pack-group]");
    expect(groups).toHaveLength(1);
    expect(within(groups[0] as HTMLElement).getAllByRole("button", { name: "workbenchMissingInstallLabel" }), "一个包一个安装").toHaveLength(1);
    expect(within(groups[0] as HTMLElement).getByRole("link", { name: "workbenchMissingPackPage" }).getAttribute("href"))
      .toBe("https://registry.comfy.org/nodes/comfyroll");
    const prompt = within(groups[0] as HTMLElement).getByText("CR Prompt Text").closest("li")!;
    fireEvent.click(within(prompt).getByRole("button", { name: "workbenchLocateLabel" }));
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "locate", node: "7", subgraph: null }));
    fireEvent.click(within(prompt).getByRole("button", { name: "workbenchLocateLabel" }));
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "locate", node: "8", subgraph: null }));
    expect(within(prompt).getByRole("button", { name: "workbenchLocateLabel" }).textContent).toContain("2/2");
  });

  it("缺的模型:点卡片也能定位;在子图里而这版前端进不了子图,就说在哪张子图里", async () => {
    const bridge = await missingTab();
    const card = within(column()).getByText("i2v-high.safetensors").closest("li")!;
    fireEvent.click(within(card).getByText("checkpoints"));
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "locate", node: "4", subgraph: null }));
    fireEvent.click(within(card).getByRole("button", { name: "workbenchLocateLabel" }));
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "locate", node: "5", subgraph: SUB }));
    expect(await within(card).findByText("workbenchLocateInSubgraph")).toBeTruthy();
  });

  it("没写下载地址:按文件名找,文件名一致的排前面;点一个候选 → 认一下 → 就地确认(这一格的目录、文件名都填好)→ 下载 → 下完自己重新检查", async () => {
    await missingTab();
    api.searchModelSources.mockResolvedValue({
      filename: "i2v-high.safetensors",
      candidates: [
        { source: "huggingface", repo: "acme/wan", title: "acme/wan", filename: "i2v-high.safetensors",
          url: "https://huggingface.co/acme/wan/resolve/main/i2v-high.safetensors", page: "https://huggingface.co/acme/wan",
          size: 14_000_000_000, base_model: "Wan 2.2", exact: true },
        { source: "civitai", repo: "Wan i2v", title: "Wan i2v · fp16", filename: "i2v-high-fp16.safetensors",
          url: "https://civitai.com/api/download/models/42", page: "https://civitai.com/models/7", size: null, base_model: "", exact: false },
      ],
      failed: [{ source: "modelscope", message: "timeout" }],
    });
    //: Civitai 一个版本有几个文件时,认出来的名字是「名字_文件号」:下下来要用候选的(= 工作流要的)名字
    api.resolveModelLink.mockResolvedValue({ source: "huggingface", url: "https://huggingface.co/acme/wan/resolve/main/i2v-high.safetensors",
                                             filename: "i2v-high_33262.safetensors", exists: false, uses_token: false, note: "" });
    api.startModelDownload.mockResolvedValue({ id: "job-3", status: "queued" });
    api.getJob.mockResolvedValue({ id: "job-3", status: "succeeded" });
    const card = within(column()).getByText("i2v-high.safetensors").closest("li")!;
    fireEvent.click(within(card).getByRole("button", { name: "workbenchSearchSourcesLabel" }));
    await waitFor(() => expect(api.searchModelSources).toHaveBeenCalledWith("i1", "i2v-high.safetensors", "checkpoints"));
    const candidates = await within(card).findByRole("list", { name: "workbenchSearchResults" });
    expect([...candidates.querySelectorAll("[data-candidate]")].map((one) => one.getAttribute("data-candidate"))).toEqual(["exact", "similar"]);
    expect(within(card).getByText("workbenchSearchFailed"), "没搜成的那家说一声").toBeTruthy();
    expect(within(card).getByRole("textbox", { name: "workbenchDownloadLink" }), "贴链接那一格一直在").toBeTruthy();
    fireEvent.click(within(candidates).getAllByRole("button")[0]);
    await waitFor(() => expect(api.resolveModelLink).toHaveBeenCalledWith("i1", "https://huggingface.co/acme/wan/resolve/main/i2v-high.safetensors"));
    const confirm = await within(card).findByRole("group", { name: "workbenchDownloadConfirm" });
    expect(api.startModelDownload).not.toHaveBeenCalled();
    fireEvent.click(within(confirm).getByRole("button", { name: /workbenchDownloadStart/ }));
    await waitFor(() => expect(api.startModelDownload).toHaveBeenCalledWith("i1", {
      workspace_id: "w1", url: "https://huggingface.co/acme/wan/resolve/main/i2v-high.safetensors", folder: "checkpoints",
      filename: "i2v-high.safetensors",
    }));
    await waitFor(() => expect(api.inspectWorkflowImport, "下完自己重新检查").toHaveBeenCalledTimes(2));
  });

  it("什么都没搜到:说没找到,贴链接就在这儿;工作流写了下载地址的直接一个「下载」", async () => {
    await missingTab();
    api.searchModelSources.mockResolvedValue({ filename: "i2v-high.safetensors", candidates: [], failed: [] });
    const card = within(column()).getByText("i2v-high.safetensors").closest("li")!;
    fireEvent.click(within(card).getByRole("button", { name: "workbenchSearchSourcesLabel" }));
    expect(await within(card).findByText("workbenchSearchNothing")).toBeTruthy();
    expect(within(card).getByRole("textbox", { name: "workbenchDownloadLink" })).toBeTruthy();

    api.inspectWorkflowImport.mockResolvedValue({ missing_nodes: [], missing_models: [
      { folder: "loras", name: "x.safetensors", url: "https://huggingface.co/a/b/resolve/main/x.safetensors" }] });
    fireEvent.click(within(column()).getByRole("button", { name: /workbenchMissingCheck/ }));
    const download = await within(column()).findByRole("button", { name: "workbenchMissingDownloadLabel" });
    expect(within(column()).queryByRole("button", { name: "workbenchSearchSourcesLabel" }), "写了地址就不用找").toBeNull();
    api.resolveModelLink.mockResolvedValue({ source: "huggingface", url: "https://huggingface.co/a/b/resolve/main/x.safetensors",
                                             filename: "x.safetensors", exists: false, uses_token: false, note: "" });
    fireEvent.click(download);
    await waitFor(() => expect(api.resolveModelLink).toHaveBeenCalledWith("i1", "https://huggingface.co/a/b/resolve/main/x.safetensors"));
    expect(await within(column()).findByRole("group", { name: "workbenchDownloadConfirm" })).toBeTruthy();
  });

  it("没有 ComfyUI-Manager:说认不出、也装不了", async () => {
    api.getWorkflowLibrary.mockResolvedValue({ workflows: [], manager: { version: "" } });
    await missingTab();
    expect(await within(column()).findByText("workbenchMissingNoManager")).toBeTruthy();
  });
});

describe("助手(ADR 0042):共用的智能体面板停靠在这一列里", () => {
  const context = () => (agent.props!.contextLine as () => string)();
  beforeEach(() => {
    agent.props = null;
    agent.reply = "";
    agent.tool = "";
    agent.data = null;
  });

  it("第五个页签;面板停靠在列里、不浮也不关,会话在开工作台的那个工作区", async () => {
    await mount();
    expect(screen.getAllByRole("tab").map((one) => one.textContent)).toEqual(
      ["workbenchTabModels", "workbenchTabMissing", "workbenchTabApp", "workbenchTabRun", "workbenchTabAssistant"]);
    expect(agent.props, "没去过的页签不挂").toBeNull();
    tab("workbenchTabAssistant");
    expect(shownPanel().querySelector("[data-agent-chat]")).toBeTruthy();
    expect(agent.props).toMatchObject({ mode: "docked", dockedLayout: "inline", workspaceId: "w1" });
    expect(agent.props!.onModeChange, "没有「浮起来」").toBeUndefined();
    expect(agent.props!.onClose, "没有关闭键:换个页签就收起来了").toBeUndefined();
    expect(shownPanel().hasAttribute("data-workbench-scroll"), "对话自己滚,这一层不滚").toBe(false);
  });

  it("页面上下文发送那一刻才取:哪台 ComfyUI、版本、开着哪一张、改没改、选中了谁;不放整张图", async () => {
    const bridge = await mount();
    tab("workbenchTabAssistant");
    expect(typeof agent.props!.contextLine).toBe("function");
    const first = context();
    for (const piece of ["ComfyUI「ComfyUI · 192.168.3.15」", "instance_id=i1", "ComfyUI 0.39.0,前端 1.53.10",
                         "「古风」(workflows/人像/古风.json),有没存的改动", "选中的节点:#4 CheckpointLoaderSimple「Load Checkpoint」",
                         "comfy_canvas_read"]) {
      expect(first, piece).toContain(piece);
    }
    expect(first.match(/instance_id=i1/g), "工具都带上连接 id").toHaveLength(2);
    expect(first, "控件的值、整张图都不在上下文里").not.toContain("sdxl.safetensors");
    bridge.emit(state({ workflow: { path: "", name: "Unsaved Workflow", temporary: true, modified: false,
                                    key: "workflows/Unsaved Workflow.json", revision: 2 },
                        selection: { count: 3, node: null }, server: { comfyui: "", frontend: "" } }));
    const later = context();
    expect(later).toContain("没存过的「Unsaved Workflow」,没有没存的改动");
    expect(later).toContain("选中的节点:3 个");
    expect(later).toContain("版本还没读到");
  });

  it("画布上的运行报错写进上下文(在 ComfyUI 里点的运行也算);之后又跑成了就不提", async () => {
    const bridge = await mount();
    tab("workbenchTabAssistant");
    bridge.emit(state({ events: [{ type: "execution_error", at: 1, promptId: "p1", node: "3", nodeType: "KSampler",
                                   message: "Expected all tensors to be on the same device" }] }));
    expect(context()).toContain("画布上最近一次运行在 #3(KSampler)报错:Expected all tensors to be on the same device");
    bridge.emit(state({ events: [{ type: "execution_success", at: 2, promptId: "p2", node: "" }] }));
    expect(context()).not.toContain("报错");
  });

  it("在工作台里跑这一张失败了:带上任务号和原因,诊断时交给 comfy_check", async () => {
    await mount();
    api.runCanvas.mockResolvedValue({ generation: { id: "g1", kind: "image" }, job: { id: "job-7", status: "queued" } });
    api.getJob.mockResolvedValue({ ...SUCCEEDED, id: "job-7", status: "failed", result: null,
                                   error: "ComfyUI 拒绝了这张工作流:#3 Value not in list: sampler_name" });
    api.getCanvasApp.mockResolvedValue(appData());
    fireEvent.click(screen.getByRole("button", { name: /workbenchRun/ }));
    await waitFor(() => expect(api.runCanvas).toHaveBeenCalled());
    tab("workbenchTabAssistant");
    await waitFor(() => expect(context()).toContain(
      "上次在工作台里运行这一张失败了(job_id=job-7):ComfyUI 拒绝了这张工作流:#3 Value not in list: sampler_name"));
  });

  it("回复里的 #4、#459:451 点了在画布上定位(子图里的交给桥一层层打开);画布上没有就在旁边说;代码里的不动", async () => {
    agent.reply = "看 #4 的 ckpt_name,子图里的 #459:451 缺模型;`#9` 只是代码。";
    const bridge = await mount();
    bridge.comfyWorkbench.mockImplementation(async ({ call }: { call: ComfyWorkbenchCall }) =>
      call.op === "locate" && call.node === "4" ? { ok: false, error: "noNode" } : { ok: true });
    tab("workbenchTabAssistant");
    const inner = await screen.findByRole("button", { name: "#459:451" });
    fireEvent.click(inner);
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "locate", node: "459:451", subgraph: null }));
    expect(within(shownPanel()).queryByRole("status")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "#4" }));
    expect(await within(shownPanel()).findByRole("status")).toHaveProperty("textContent", "画布上没有节点 #4");
    expect(screen.queryByRole("button", { name: "#9" }), "代码里的不变成定位").toBeNull();
    expect(screen.getByText("#9").tagName).toBe("CODE");
  });
});

describe("助手(ADR 0042 第二步):诊断的「定位」「照这个改」、改完的、新标签页的「去下载」", () => {
  const MISSING = { ref: "459:451", type: "UNETLoader", severity: "error", kind: "missing_model", input: "unet_name",
                    cause: "这台机器上没有模型文件「qwen.safetensors」", fix: "下载它到 diffusion_models" };
  const OOM = { ref: "", type: "", severity: "error", kind: "last_run_error", cause: "out of memory", fix: "调小宽高" };
  beforeEach(() => {
    agent.props = null;
    agent.reply = "";
    agent.tool = "";
    agent.data = null;
  });
  const result = () => shownPanel().querySelector<HTMLElement>("[data-tool-result]")!;

  it("诊断一条一条画出来:「定位」经桥选中那个节点(子图里的一层层打开);指不到节点的那条没有「定位」", async () => {
    agent.tool = "comfy_check";
    agent.data = { findings: [MISSING, OOM], counts: { error: 2, warning: 0 } };
    const bridge = await mount();
    bridge.comfyWorkbench.mockImplementation(async () => ({ ok: true }));
    tab("workbenchTabAssistant");
    const rows = within(result()).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("#459:451");
    expect(rows[0].textContent).toContain("这台机器上没有模型文件「qwen.safetensors」");
    expect(within(rows[1]).queryByRole("button", { name: /workbenchLocateLabel/ }), "整张图的报错指不到节点").toBeNull();
    fireEvent.click(within(rows[0]).getByRole("button", { name: /workbenchLocateLabel/ }));
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "locate", node: "459:451", subgraph: null }));
  });

  it("没查出问题就不出结果行:工具行(✓ comfy_check)已证明跑过,回答由智能体自己说", async () => {
    agent.tool = "comfy_check";
    agent.data = { findings: [], counts: { error: 0, warning: 0 } };
    await mount();
    tab("workbenchTabAssistant");
    //: 既没有卡片,也没有那行安静的确认 —— 零发现的工具回包不是内容。
    expect(result().querySelector("[data-comfy-findings]")).toBeNull();
  });

  it("「照这个改」替用户发一句(带着这一条),智能体据此提一次 comfy_canvas_edit;面板接走就清掉", async () => {
    agent.tool = "comfy_check";
    agent.data = { findings: [MISSING], counts: { error: 1, warning: 0 } };
    const bridge = await mount();
    tab("workbenchTabAssistant");
    expect(agent.props!.outbox).toBeNull();
    fireEvent.click(within(result()).getByRole("button", { name: /让助手照这一条改/ }));
    await waitFor(() => expect(agent.props!.outbox).toBeTruthy());
    const outbox = agent.props!.outbox as { text: string; context: string };
    expect(outbox.text).toBe("照这个改:#459:451 UNETLoader:这台机器上没有模型文件「qwen.safetensors」");
    expect(outbox.context).toContain("comfy_canvas_edit");
    expect(outbox.context).toContain(JSON.stringify(MISSING));
    expect(calls(bridge).filter((one) => one.op !== "export"), "点「照这个改」不碰画布").toEqual([]);
    act(() => (agent.props!.onOutboxTaken as () => void)());
    await waitFor(() => expect(agent.props!.outbox).toBeNull());
  });

  it("改完的:改了几处、修好了几个、多出来的提醒也能定位", async () => {
    agent.tool = "comfy_canvas_edit";
    agent.data = { applied: 3, fixed: [MISSING], introduced: [{ ...MISSING, ref: "5", severity: "warning", kind: "size_not_multiple",
                                                                cause: "「width」= 1001 不是 8 的倍数" }] };
    await mount();
    tab("workbenchTabAssistant");
    expect(result().querySelector("[data-comfy-applied]")!.textContent).toContain("workbenchAppliedSummary");
    expect(within(result()).getAllByRole("listitem")).toHaveLength(1);
    expect(within(result()).getByRole("listitem").textContent).toContain("「width」= 1001 不是 8 的倍数");
  });

  it("新标签页:开了哪一张、没存盘、还缺几个模型合计多大;「去下载」换到缺失项那一页", async () => {
    api.getWorkflowLibrary.mockResolvedValue({ workflows: [], manager: { version: "V4.2.1" } });
    api.inspectWorkflowImport.mockResolvedValue({ missing_nodes: [], packs: [], missing_models: [] });
    agent.tool = "comfy_canvas_new";
    agent.data = { saved: false, opened: { name: "Qwen 编辑", temporary: true, path: "" },
                   template: { name: "image_qwen_image_2_1_image_edit", missing_size: 26_754_163_364, models: [
                     { name: "qwen_image_2.1_int8_convrot.safetensors", folder: "diffusion_models", status: "missing", size: 20_000_000_000 },
                     { name: "vae.safetensors", folder: "vae", status: "present" }] },
                   check: { counts: { error: 4, warning: 0 }, findings: [] } };
    await mount();
    tab("workbenchTabAssistant");
    const card = result().querySelector<HTMLElement>("[data-comfy-new-tab]")!;
    expect(card.textContent).toContain("workbenchNewTabOpened");
    expect(card.textContent).toContain("qwen_image_2.1_int8_convrot.safetensors");
    expect(card.textContent).not.toContain("vae.safetensors");
    fireEvent.click(within(card).getByRole("button", { name: /workbenchGoDownload/ }));
    expect(screen.getByRole("tab", { name: "workbenchTabMissing" }).getAttribute("aria-selected")).toBe("true");
  });

  it("不认得的工具结果:这一页不画(工具行照通用的画)", async () => {
    agent.tool = "comfy_templates";
    agent.data = { templates: [] };
    await mount();
    tab("workbenchTabAssistant");
    expect(result().textContent).toBe("");
  });
});
