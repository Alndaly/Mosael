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
 * - 这版前端缺了哪一样,那一处说「不支持」,别的照常。
 *
 * 版式、拉宽、换工作流、定位、找下载地址各有一组(在后面)。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
vi.mock("@/app/preferences", () => ({
  //: 「结果取自 {nodes}」留着占位:看得出填进去的节点名
  useI18n: () => (key: string) => (key === "workbenchRunResultsFrom" ? "workbenchRunResultsFrom {nodes}" : key),
  usePreferences: () => ({ locale: "zh" }),
}));

import type { WorkflowApp } from "@/api/client";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { installAppChromeGuards } from "@/components/ui/appChrome";
import { declaresDrag, noDragAfter } from "@/test/dragRegions";
import { COLUMN_DEFAULT, COLUMN_MIN, DRAG_GUARD } from "./columnWidth";
import { ComfyWorkbench } from "./ComfyWorkbench";
import { RECHECK_DELAY_MS } from "./MissingPanel";
import { openWorkbench, resetWorkbench } from "./workbenchSession";

const TARGET = { instanceId: "i1", instanceName: "ComfyUI · 192.168.3.15", workspaceId: "w1", url: "http://192.168.3.15:8188" };
const CAPS = { selection: true, setWidget: true, refreshCombos: true, export: true, dirty: true, save: true, events: true, marks: true,
               changes: true, locate: true, subgraphs: true, readGraph: true };
const LOADER = { id: "4", type: "CheckpointLoaderSimple", title: "Load Checkpoint",
                 widgets: [{ name: "ckpt_name", type: "combo", value: "sdxl.safetensors", combo: true }] };
const EXPORTED = {
  workflow: { nodes: [{ id: 4, type: "CheckpointLoaderSimple", widgets_values: ["sdxl.safetensors"] }, { id: 9, type: "SaveImage", title: "高清" },
                      { id: 17, type: "PreviewImage" }] },
  prompt: { "9": { class_type: "SaveImage", inputs: {} } },
  clientId: "4f1c0e2a9b7d4c51a3e8",
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
  app: { status: "none", version: "", app: false, title: "", description: "", items: [], results: [], invalid: 0, fields: 0 },
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

afterEach(() => {
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
      "workbenchTabModels", "workbenchTabMissing", "workbenchTabApp", "workbenchTabRun",
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

  it("保存是前端自己的保存命令;没存过的工作流不能在这里跑,说为什么", async () => {
    const bridge = await mount(state({ workflow: { path: "", name: "Unsaved Workflow", temporary: true, modified: true,
                                                   key: "workflows/Unsaved Workflow.json", revision: 1 } }));
    fireEvent.click(screen.getByRole("button", { name: /workbenchSave/ }));
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "save" }));
    expect(screen.getByRole("button", { name: /workbenchRun/ }).hasAttribute("disabled")).toBe(true);
  });

  it("模型库:选中加载节点只列那个目录的模型,点一行经桥填进去;下拉里还没有就给「刷新下拉」", async () => {
    const bridge = await mount();
    await waitFor(() => expect(api.getNodeFolders).toHaveBeenCalledWith("i1", [
      { class_type: "CheckpointLoaderSimple", input: "ckpt_name", values: { ckpt_name: "sdxl.safetensors" } },
    ]));
    const list = await screen.findByRole("list", { name: "workbenchModelsList" });
    expect(within(list).getAllByRole("listitem").map((one) => one.textContent)).toEqual([
      expect.stringContaining("film grain"), expect.stringContaining("Pony"), expect.stringContaining("SDXL Base"),
    ]);
    expect(within(list).getByRole("button", { pressed: true }).textContent).toContain("SDXL Base");
    fireEvent.click(within(list).getByRole("button", { name: /film grain/ }));
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "setWidget", node: "4", widget: "ckpt_name", value: "flux-dev.safetensors" }));
    expect((await within(column()).findByRole("status")).textContent).toContain("workbenchModelsFilled");

    bridge.comfyWorkbench.mockImplementationOnce(async () => ({ ok: false, error: "notInList" }));
    fireEvent.click(within(list).getByRole("button", { name: /SDXL Base/ }));
    fireEvent.click(await screen.findByRole("button", { name: /workbenchCombosRefresh/ }));
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "refreshCombos" }));
  });

  it("模型库:选中 CLIP 加载节点时,合它现在 type 的文本编码器排前面,不在配方里的排最后、标出来;换了 type 重新问", async () => {
    const encoder = (name: string, kind: string, label: string) => ({
      folder: "text_encoders", name, family: "", family_source: "not_applicable", title: "", triggers: [], has_preview: false,
      encoder: { kind, label, source: "weights", pairs: [] },
    });
    api.getModelLibrary.mockResolvedValue({
      folders: [], missing: [], downloads: [],
      models: [encoder("a_clip_l.safetensors", "clip_l", "CLIP-L"), encoder("b_qwen.safetensors", "qwen3_06b", "Qwen3 0.6B"),
               encoder("c_umt5.safetensors", "umt5_xxl", "UMT5-XXL")],
    });
    api.getNodeFolders.mockImplementation(async (_: string, nodes: { input: string; values: Record<string, string> }[]) => ({
      folders: nodes.map((one) => (one.input === "clip_name" ? "text_encoders" : "")),
      encoders: nodes.map((one) => (one.input !== "clip_name" ? null : one.values.type === "wan"
        ? { type: "wan", fits: ["umt5_xxl"], any_type: ["qwen3_06b"] }
        : { type: "stable_diffusion", fits: ["clip_l", "clip_h", "clip_g"], any_type: ["qwen3_06b"] })),
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
    expect(api.getNodeFolders).toHaveBeenLastCalledWith("i1", expect.arrayContaining([
      { class_type: "CLIPLoader", input: "clip_name", values: { clip_name: "c_umt5.safetensors", type: "stable_diffusion" } },
    ]));
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

  it("应用:读画布上这张;改了「写进画布」—— 插件算标记、经桥改节点,不写文件", async () => {
    const bridge = await mount();
    api.getCanvasApp.mockResolvedValue(appData());
    api.getCanvasMarks.mockResolvedValue({ nodes: { "3": { expose: { steps: { order: 0 } } } }, extra: { version: 1, app: {} } });
    tab("workbenchTabApp");
    await waitFor(() => expect(api.getCanvasApp).toHaveBeenCalledWith("i1", EXPORTED.workflow));
    const write = await screen.findByRole("button", { name: /workbenchAppWrite/ });
    expect(write.hasAttribute("disabled"), "没改过不用写").toBe(true);
    //: 面板窄:编辑器是「挑项 / 表单 / 预览」三个标签,先到「挑项」里点「+」
    fireEvent.mouseDown(await screen.findByRole("tab", { name: /workflowAppTabSource/ }));
    fireEvent.click(within(document.querySelector("[data-source-item='3.steps']") as HTMLElement)
      .getByRole("button", { name: "workflowAppAdd" }));
    fireEvent.click(write);
    await waitFor(() => expect(api.getCanvasMarks).toHaveBeenCalled());
    const [, body] = api.getCanvasMarks.mock.calls[0];
    expect(body.content).toEqual(EXPORTED.workflow);
    expect(body.app.items.map((one: { node: string; input: string }) => `${one.node}.${one.input}`)).toHaveLength(1);
    await waitFor(() => expect(calls(bridge)).toContainEqual({
      op: "setMarks", marks: { nodes: { "3": { expose: { steps: { order: 0 } } } }, extra: { version: 1, app: {} } },
    }));
    expect(await screen.findByText("workbenchAppWritten")).toBeTruthy();
  });

  it("运行:跑画布上这张(API 图、界面格式、前端的 clientId);产出按来自的节点分组、标节点名;「只要这个节点的图」标在画布上", async () => {
    const bridge = await mount();
    api.runCanvas.mockResolvedValue({ generation: { id: "g1", kind: "image" }, job: { id: "job-9", status: "queued" } });
    api.getJob.mockResolvedValue(SUCCEEDED);
    api.getCanvasApp.mockResolvedValue(appData({ app: { status: "ok", version: "1", app: false, title: "", description: "", items: [],
                                                        results: ["9"], invalid: 0, fields: 0 } }));
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
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "setMarks", marks: { nodes: { "17": { result: true } }, extra: { version: 1 } } }));
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
    const toggle = within(bar).getByRole("radiogroup", { name: "comfyNavigation" });
    expect(toggle.className, "操控方式:外框和按钮一样高").toMatch(/\bh-8\b/);
    for (const one of within(toggle).getAllByRole("radio")) expect(one.className).toMatch(/\btext-ui-sm\b/);
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
    expect(document.querySelector("[data-workbench-drag-guard]"), "让出来的那一截铺一块底色").not.toBeNull();
    await waitFor(() => expect(bridge.mosaelPageTools.setInset).toHaveBeenLastCalledWith(COLUMN_DEFAULT + 100 + DRAG_GUARD));
    fireEvent.pointerMove(window, { clientX: 100, buttons: 1, pointerId: 1 });
    expect(width(), "最宽是窗口的一半(主进程也最多让出一半)").toBe(720);
    fireEvent.pointerMove(window, { clientX: 1400, buttons: 1, pointerId: 1 });
    expect(width(), "最窄 300").toBe(COLUMN_MIN);
    fireEvent.pointerUp(window, { pointerId: 1 });
    expect(document.querySelector("[data-workbench-drag-guard]")).toBeNull();
    await waitFor(() => expect(bridge.mosaelPageTools.setInset).toHaveBeenLastCalledWith(COLUMN_MIN));
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
  it("点一行:上一句话一直留着、回话到了原地换成新的一句;列表里的每一行不重挂", async () => {
    const bridge = await mount();
    const list = await screen.findByRole("list", { name: "workbenchModelsList" });
    fireEvent.click(within(list).getByRole("button", { name: /film grain/ }));
    const note = await within(column()).findByText(/workbenchModelsFilled/);
    const rows = within(list).getAllByRole("listitem");
    let answer: (value: unknown) => void = () => undefined;
    bridge.comfyWorkbench.mockImplementationOnce(() => new Promise((resolve) => (answer = resolve)) as never);
    fireEvent.click(within(list).getByRole("button", { name: /Pony/ }));
    await waitFor(() => expect(calls(bridge)).toContainEqual(expect.objectContaining({ op: "setWidget", value: "pony.safetensors" })));
    expect(note.isConnected, "填的过程中那一句不撤掉(撤掉再放回来,整个列表上下跳一下)").toBe(true);
    expect(within(list).getByRole("button", { name: /Pony/ }).getAttribute("aria-busy"), "点的那一行在转圈").toBe("true");
    await act(async () => answer({ ok: true, value: "pony.safetensors" }));
    expect(note.isConnected).toBe(true);
    expect(within(column()).getByText(/workbenchModelsFilled/), "还是同一个元素,换了内容").toBe(note);
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
      app: { status: "ok", version: "1", app: false, title: "", description: "", items: [], results: ["17"], invalid: 0, fields: 0 },
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
    const marked = (results: string[]) => appData({ app: { status: "ok", version: "1", app: false, title: "", description: "", items: [],
                                                            results, invalid: 0, fields: 0 } });
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
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "setMarks", marks: { nodes: {}, extra: { version: 1 } } }));
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
