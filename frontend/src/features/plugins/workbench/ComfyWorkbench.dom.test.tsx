/** @vitest-environment jsdom */

/**
 * ComfyUI 工作台(ADR 0038 §3、§6):画布是那台 ComfyUI 自己的(内嵌视图,这里看不见),Mosael 的顶栏和右边那一列画在旁边。
 * 主进程的桥报来的东西(选中、脏标记、能力、事件)经 `onComfyWorkbench` 到这里;面板要桥做的事经 `comfyWorkbench` 交回去。
 * 这里看的是:
 *
 * - 顶栏:连接、工作流名、有没有没存的改动、操控方式、「保存」(前端自己的命令)、「运行」(没存过的不能跑,说为什么);
 *   右边那一列开着时网页让出那么宽,收起时还回去;会话结束(视图收起)就不画了;
 * - 模型库:选中一个加载节点 → 问插件那一格是哪个目录 → 只列那个目录的模型 → 点一个经桥填进去;下拉里还没有就给「刷新下拉」;
 *   那一格选的文件这台 ComfyUI 上没有 → 贴链接、认一下、就地确认后下载;
 * - 缺失项:导出画布(含没存的)交给插件认一遍,缺的节点包「装上」先就地确认;
 * - 应用:读画布上这张的应用表单,改了「写进画布」—— 插件算出标记、经桥改节点,不写文件;
 * - 运行与结果:跑画布上这张(导出的 API 图、界面格式、前端的 clientId),产出按来自的节点分组、标节点名,「以后只要这张」;
 * - 这版前端缺了哪一样,那一处说「不支持」,别的照常。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getNodeFolders: vi.fn(),
  getModelLibrary: vi.fn(),
  resolveModelLink: vi.fn(),
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
  modelPreviewUrl: (_: string, folder: string, name: string) => `preview://${folder}/${name}`,
  modelThumbnailUrl: (_: string, folder: string, name: string) => `thumb://${folder}/${name}`,
}));
vi.mock("@/api/client", () => api);
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh" }),
}));

import type { WorkflowApp } from "@/api/client";
import { ComfyWorkbench, WORKBENCH_COLUMN_WIDTH } from "./ComfyWorkbench";
import { openWorkbench, resetWorkbench } from "./workbenchSession";

const TARGET = { instanceId: "i1", instanceName: "ComfyUI · 192.168.3.15", workspaceId: "w1", url: "http://192.168.3.15:8188" };
const CAPS = { selection: true, setWidget: true, refreshCombos: true, export: true, dirty: true, save: true, events: true, marks: true };
const LOADER = { id: "4", type: "CheckpointLoaderSimple", title: "Load Checkpoint",
                 widgets: [{ name: "ckpt_name", type: "combo", value: "sdxl.safetensors", combo: true }] };
const EXPORTED = {
  workflow: { nodes: [{ id: 4, type: "CheckpointLoaderSimple" }, { id: 9, type: "SaveImage", title: "高清" },
                      { id: 17, type: "PreviewImage" }] },
  prompt: { "9": { class_type: "SaveImage", inputs: {} } },
  clientId: "4f1c0e2a9b7d4c51a3e8",
};

function state(overrides: Partial<ComfyWorkbenchState> = {}): ComfyWorkbenchState {
  return {
    capabilities: { ...CAPS },
    workflow: { path: "人像/古风.json", name: "古风", temporary: false, modified: true },
    selection: { count: 1, node: LOADER },
    clientId: EXPORTED.clientId,
    events: [],
    ...overrides,
  };
}

/** 桌面版的几座桥:工作台的(开、做事、收到桥那边的)、页面工具的让位、顶栏的返回、操控方式。 */
function desktop() {
  let listener: ((update: { connectionId: string; state: ComfyWorkbenchState | null }) => void) | null = null;
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
    mosaelPageTools: { setInset: vi.fn(async () => undefined) },
    mosaelPublish: { hideView: vi.fn(async () => undefined) },
  };
  for (const [name, value] of Object.entries(bridges)) vi.stubGlobal(name, value);
  const emit = (next: ComfyWorkbenchState | null) => act(() => listener?.({ connectionId: "i1", state: next }));
  return { ...bridges, comfyWorkbench, emit };
}

async function mount(first: ComfyWorkbenchState | null = state()) {
  const bridge = desktop();
  await openWorkbench(TARGET, { path: "人像/古风.json" });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <ComfyWorkbench barHeight={56} />
    </QueryClientProvider>,
  );
  if (first) bridge.emit(first);
  return { ...bridge, view };
}

const calls = (bridge: { comfyWorkbench: ReturnType<typeof vi.fn> }) =>
  bridge.comfyWorkbench.mock.calls.map(([one]) => (one as { call: ComfyWorkbenchCall }).call);
const tab = (name: string) => fireEvent.click(screen.getByRole("tab", { name }));
const column = () => screen.getByRole("complementary", { name: "workbenchColumn" });

const appData = (overrides: Partial<WorkflowApp> = {}): WorkflowApp => ({
  path: "", modified: null, kind: "image", editable: true,
  items: [
    { key: "6.text", node: "6", input: "text", kind: "text", role: "prompt", title: "提示词", node_title: "", node_label: "CLIP 文本编码",
      hint: "", class_type: "CLIPTextEncode", common: true, media: "", folder: "", exposable: true, spec: { type: "string", default: "a girl" } },
    { key: "3.steps", node: "3", input: "steps", kind: "number", title: "步数", node_title: "采样", node_label: "采样", hint: "",
      class_type: "KSampler", common: true, role: "", media: "", folder: "", exposable: true, spec: { type: "integer", default: 20 } },
  ],
  outputs: [{ node: "9", title: "高清", label: "高清", class_type: "SaveImage", media: "image" }],
  app: { status: "none", version: "", app: false, title: "", description: "", items: [], results: [], invalid: 0, fields: 0 },
  ...overrides,
});

beforeEach(() => {
  window.localStorage.clear();
  for (const fn of Object.values(api)) if (typeof fn === "function" && "mockReset" in fn) (fn as ReturnType<typeof vi.fn>).mockReset();
  api.getNodeFolders.mockResolvedValue({ folders: ["checkpoints"] });
  api.getModelLibrary.mockResolvedValue({
    folders: [], missing: [], downloads: [],
    models: [
      { folder: "checkpoints", name: "sdxl.safetensors", family: "SDXL", title: "SDXL Base", triggers: [], has_preview: false },
      { folder: "checkpoints", name: "flux-dev.safetensors", family: "Flux", title: "", triggers: ["film grain"], has_preview: false },
      { folder: "loras", name: "style.safetensors", family: "SDXL", title: "", triggers: [], has_preview: false },
    ],
  });
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

afterEach(() => {
  resetWorkbench();
  vi.unstubAllGlobals();
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
    expect(bridge.mosaelPageTools.setInset).toHaveBeenLastCalledWith(WORKBENCH_COLUMN_WIDTH);
    expect(within(column()).getAllByRole("tab").map((one) => one.textContent)).toEqual([
      "workbenchTabModels", "workbenchTabMissing", "workbenchTabApp", "workbenchTabRun",
    ]);
    fireEvent.click(within(bar).getByRole("button", { name: "workbenchColumnHide" }));
    expect(bridge.mosaelPageTools.setInset).toHaveBeenLastCalledWith(0);
    expect(screen.queryByRole("complementary", { name: "workbenchColumn" })).toBeNull();
    fireEvent.click(within(bar).getByRole("button", { name: "workbenchColumnShow" }));
    expect(bridge.mosaelPageTools.setInset).toHaveBeenLastCalledWith(WORKBENCH_COLUMN_WIDTH);
    fireEvent.click(within(bar).getByRole("button", { name: /publishBackToApp/ }));
    expect(bridge.mosaelPublish.hideView).toHaveBeenCalled();
    bridge.emit(null);
    expect(document.querySelector("[data-comfy-workbench-bar]")).toBeNull();
  });

  it("保存是前端自己的保存命令;没存过的工作流不能在这里跑,说为什么", async () => {
    const bridge = await mount(state({ workflow: { path: "", name: "Unsaved Workflow", temporary: true, modified: true } }));
    fireEvent.click(screen.getByRole("button", { name: /workbenchSave/ }));
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "save" }));
    expect(screen.getByRole("button", { name: /workbenchRun/ }).hasAttribute("disabled")).toBe(true);
  });

  it("模型库:选中加载节点只列那个目录的模型,点一个经桥填进去;下拉里还没有就给「刷新下拉」", async () => {
    const bridge = await mount();
    await waitFor(() => expect(api.getNodeFolders).toHaveBeenCalledWith("i1", [{ class_type: "CheckpointLoaderSimple", input: "ckpt_name" }]));
    const list = await screen.findByRole("list", { name: "workbenchModelsList" });
    expect(within(list).getAllByRole("button").map((one) => one.textContent)).toEqual([
      expect.stringContaining("film grain"), expect.stringContaining("SDXL Base"),
    ]);
    expect(within(list).getByRole("button", { pressed: true }).textContent).toContain("SDXL Base");
    fireEvent.click(within(list).getByRole("button", { name: /film grain/ }));
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "setWidget", node: "4", widget: "ckpt_name", value: "flux-dev.safetensors" }));
    expect((await screen.findByRole("status")).textContent).toContain("workbenchModelsFilled");

    bridge.comfyWorkbench.mockImplementationOnce(async () => ({ ok: false, error: "notInList" }));
    fireEvent.click(within(list).getByRole("button", { name: /SDXL Base/ }));
    fireEvent.click(await screen.findByRole("button", { name: /workbenchCombosRefresh/ }));
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "refreshCombos" }));
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
    api.resolveModelLink.mockResolvedValue({ url: "https://huggingface.co/a/b/resolve/main/gone.safetensors", filename: "gone.safetensors",
                                             exists: false });
    api.startModelDownload.mockResolvedValue({ id: "job-1", status: "queued" });
    api.getJob.mockResolvedValue({ id: "job-1", status: "running", message: "1.2 MB" });
    fireEvent.change(screen.getByRole("textbox", { name: "workbenchDownloadLink" }), {
      target: { value: "https://huggingface.co/a/b/blob/main/gone.safetensors" },
    });
    fireEvent.click(screen.getByRole("button", { name: /workbenchDownloadResolve/ }));
    const confirm = await screen.findByRole("group", { name: "workbenchDownloadConfirm" });
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
    expect(screen.getByText("workbenchMissingNoUrl"), "没写下载地址的说去模型库面板贴链接").toBeTruthy();
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

  it("运行:跑画布上这张(API 图、界面格式、前端的 clientId);产出按来自的节点分组、标节点名;「以后只要这张」标在画布上", async () => {
    const bridge = await mount();
    api.runCanvas.mockResolvedValue({ generation: { id: "g1" }, job: { id: "job-9", status: "queued" } });
    api.getJob.mockResolvedValue({
      id: "job-9", status: "succeeded", message: "", error: null,
      result: { asset_ids: ["a1", "a2"], output_parameters: [{ asset_id: "a1", parameters: { source_node: "17" } },
                                                              { asset_id: "a2", parameters: { source_node: "9" } }] },
    });
    api.getCanvasApp.mockResolvedValue(appData({ app: { status: "ok", version: "1", app: false, title: "", description: "", items: [],
                                                        results: ["9"], invalid: 0, fields: 0 } }));
    api.getCanvasMarks.mockResolvedValue({ nodes: { "17": { result: true } }, extra: { version: 1 } });
    fireEvent.click(screen.getByRole("button", { name: /workbenchRun/ }));
    await waitFor(() => expect(api.runCanvas).toHaveBeenCalledWith("i1", {
      workspace_id: "w1", path: "人像/古风.json", prompt: EXPORTED.prompt, workflow: EXPORTED.workflow, client_id: EXPORTED.clientId,
    }));
    const preview = await screen.findByRole("region", { name: "PreviewImage #17" });
    expect(within(preview).getByRole("img").getAttribute("src")).toBe("thumb://a1");
    expect(screen.getByRole("region", { name: "高清 #9" })).toBeTruthy();
    fireEvent.click(within(preview).getByRole("button", { name: "workbenchRunOnlyThisLabel" }));
    await waitFor(() => expect(api.getCanvasMarks).toHaveBeenCalled());
    expect(api.getCanvasMarks.mock.calls[0][1].results, "只标这一个,清掉别的").toEqual(["17"]);
    await waitFor(() => expect(calls(bridge)).toContainEqual({ op: "setMarks", marks: { nodes: { "17": { result: true } }, extra: { version: 1 } } }));
    expect(await screen.findByText("workbenchRunMarked")).toBeTruthy();
  });

  it("运行:刚存的那张宿主的目录还没刷新到(422)就刷新一次再试", async () => {
    await mount();
    api.runCanvas.mockRejectedValueOnce(Object.assign(new Error("还不是生成模型"), { status: 422 }))
      .mockResolvedValueOnce({ generation: { id: "g1" }, job: { id: "job-9", status: "queued" } });
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
