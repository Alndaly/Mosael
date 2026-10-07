/** @vitest-environment jsdom */

/**
 * 工作流库(ADR 0035):一个连接那台服务器上存着的工作流,和模型库同一套骨架(LibraryBrowser)。数据是
 * `/workflow-library` 给的,这里看的是怎么摆:
 *
 * - 左边一列是那台机器上 workflows/ 的文件夹树(按名字排、子文件夹缩进、空的也在、数量连同子文件夹),钉在底部的
 *   「缺节点或模型」;选一个文件夹只看它和它下面的,搜索框说在哪个文件夹里、几张;顶上搜索、按种类筛、排序、三档显示方式;
 * - 文件夹:新建、改名(里面几张跟着换路径)、删除(只删空的;不空的点不了、说为什么;后端现查到不空照实说);卡片拖到
 *   左边的文件夹上就是移过去(先确认);
 * - 卡片 / 列表的一行:右键、悬停出现的 ⋯、Shift+F10 / 菜单键打开同一份菜单,分组摆好,点不了的写着为什么;
 *   「移动到…」挑文件夹;「下载缺的模型」「装缺的节点」打开详情停到那一节;
 * - 一张卡:节点图缩略预览(照图摘要画成 SVG)、名字、种类、节点数、缺什么;
 * - 点开是详情:能填什么 / 参数 / 交出什么、用到的模型(在不在)、缺的节点(出自哪个节点包、装没装)和缺的模型、
 *   最近的产出、Mosael 里谁在用它(点了跳过去);「用它生成」交给 AI 工作台,不是生成模型的点不了并说为什么;
 * - 改那台机器上的文件(复制、改名、删除、恢复)每次都先确认、写明改哪台服务器的哪个文件;撞名(409)不覆盖,给建议名;
 *   删除是挪进回收目录,确认框里说清楚 Mosael 里谁在用它;「回收站」里能恢复;导出 JSON 只是下载到本机;
 * - 打开一张只有一个入口:桌面版「在工作台里打开」(工作台里开 ComfyUI 的画布并打开这一张),网页版「在 ComfyUI 里打开」
 *   (新标签页,说清楚在哪点开);「新建」同样。回到 Mosael 时刷新(在 ComfyUI 里存了改动、换了模型,这边跟着变);
 * - 和模型库互相跳:用到的模型点了停到模型库那一项,缺的点了去模型库下载;从模型库跳过来停到那一张;
 * - 补齐缺的节点:装了 ComfyUI-Manager 的,没装的节点包旁边能「装上」(先确认:改哪台机器、要重启);装好了、或者装了
 *   却没加载的,给「重启 ComfyUI」(也先确认),重启完重新列;没装 Manager 就说在那台机器上手动装。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const openImagePreview = vi.hoisted(() => vi.fn());
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview, isImagePreviewOpen: false }) }));

import { installAppChromeGuards } from "@/components/ui/appChrome";

const api = vi.hoisted(() => ({
  getWorkflowLibrary: vi.fn(),
  getWorkflowContent: vi.fn(),
  copyWorkflow: vi.fn(),
  renameWorkflow: vi.fn(),
  trashWorkflow: vi.fn(),
  restoreWorkflow: vi.fn(),
  createWorkflowFolder: vi.fn(),
  renameWorkflowFolder: vi.fn(),
  trashWorkflowFolder: vi.fn(),
  refreshPluginInstance: vi.fn(),
  startNodeInstall: vi.fn(),
  rebootWorkflowServer: vi.fn(),
  getJob: vi.fn(),
  assetThumbnailUrl: (id: string) => `thumb://${id}`,
  assetPreviewUrl: (id: string) => `preview://${id}`,
  assetFileUrl: (id: string) => `file://${id}`,
  getAsset: vi.fn(async (id: string) => ({ id, kind: id.startsWith("v") ? "video" : "image", name: `产出 ${id}` })),
}));
const saved = vi.hoisted(() => vi.fn());
vi.mock("@/lib/download", () => ({ saveJsonToDisk: saved }));
vi.mock("@/api/client", () => api);
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh" }),
}));
const handoff = vi.hoisted(() => vi.fn());
vi.mock("@/lib/generationHandoff", () => ({ handOffToGeneration: handoff }));

import type { PluginInstance, WorkflowFile, WorkflowLibrary } from "@/api/client";
import { ConnectionLibraries } from "./ConnectionLibraries";
import { WorkflowLibraryDialog } from "./WorkflowLibrary";
import { resetWorkbench } from "./workbench/workbenchSession";

const instance = { id: "i1", name: "ComfyUI · 192.168.3.15", blocked_reason: "" } as PluginInstance;

function flow(overrides: Partial<WorkflowFile>): WorkflowFile {
  return {
    path: "x.json", label: "x", folder: "", size: 100, modified: 1776098682, kind: "image", problem: "", node_count: 3,
    graph: {
      nodes: [
        { x: 0, y: 0, w: 300, h: 100, role: "model", muted: false, title: "Load Checkpoint" },
        { x: 400, y: 0, w: 300, h: 260, role: "sampler", muted: false, title: "KSampler" },
        { x: 800, y: 0, w: 300, h: 260, role: "output", muted: true, title: "Save Image" },
      ],
      links: [[0, 1], [1, 2]],
      groups: [{ x: -20, y: -40, w: 1140, h: 320, title: "出图", color: "#3f789e" }],
      auto_layout: false, truncated: false,
    },
    inputs: [], parameters: [], outputs: [], models: [], missing_nodes: [], missing_models: [],
    generation: null, last_output: null, used_by: [],
    ...overrides,
  } as WorkflowFile;
}

function library(overrides: Partial<WorkflowLibrary> = {}): WorkflowLibrary {
  return {
    workflows: [
      flow({
        path: "portrait.json", label: "portrait", modified: 1776098690,
        inputs: [{ node: "10", title: "LoadImage", media: "image", role: "reference_image" }],
        parameters: [{ key: "3.steps", title: "步数", type: "integer" }],
        outputs: [{ node: "9", title: "保存图像", media: "image" }],
        models: [{ folder: "checkpoints", name: "sdxl.safetensors", present: true },
                 { folder: "loras", name: "gone.safetensors", present: false }],
        missing_models: [{ folder: "loras", name: "gone.safetensors", url: "https://huggingface.co/x/y/resolve/main/gone.safetensors" }],
        generation: { provider_profile_id: "p9", kind: "image", model: "portrait.json" },
        last_output: { asset_id: "a1", created_at: "2026-10-05T10:00:00" },
        used_by: [{ kind: "workflow", id: "w1", name: "出图流程" }, { kind: "board", id: "b1", name: "分镜板" }],
      }),
      flow({ path: "video/wan.json", label: "wan", folder: "video", kind: "video", node_count: 7, modified: 1776098600,
             generation: { provider_profile_id: "p9", kind: "video", model: "video/wan.json" },
             graph: { nodes: [{ x: 0, y: 0, w: 300, h: 120, role: "model", muted: false, title: "A" }], links: [], groups: [],
                      auto_layout: true, truncated: false } }),
      flow({ path: "sub/sketch.json", label: "sketch", folder: "sub", kind: "", node_count: 12, modified: 1776098500,
             problem: "这台 ComfyUI 上没有这几种节点:CR Prompt Text",
             missing_nodes: [
               { type: "CR Prompt Text", count: 2, packs: [{ id: "ComfyUI_Comfyroll_CustomNodes", title: "Comfyroll Studio", installed: false }] },
               { type: "Display Any (rgthree)", count: 1, packs: [{ id: "rgthree-comfy", title: "rgthree", installed: true }] },
             ] }),
    ],
    others: [{ path: "pack.zip", reason: "这是一个压缩包" }],
    trash: [],
    manager: { version: "V4.2.1" },
    ...overrides,
  };
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(node, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
}

async function openLibrary() {
  wrap(<ConnectionLibraries instance={instance} workspaceId="w1" workflows />);
  fireEvent.click(screen.getByRole("button", { name: "workflowLibraryOpen" }));
  return await screen.findByRole("list", { name: "workflowLibraryTitle" });
}

const cards = () => within(screen.getByRole("list", { name: "workflowLibraryTitle" })).getAllByRole("listitem");
const names = () => cards().map((card) => card.querySelector("[data-library-open]")?.textContent);
const folderTab = (name: string) => within(screen.getByRole("tablist", { name: "workflowLibraryFolders" })).getByRole("tab", { name });

async function openDetail(name: string) {
  await openLibrary();
  const card = cards().find((item) => item.textContent?.includes(name))!;
  fireEvent.click(within(card).getByRole("button", { name }));
  return await screen.findByRole("button", { name: "workflowLibraryBack" });
}

/** 后端撞名回的那种 409:`detail` 里带着建议名。 */
function conflict(suggestion: string) {
  return Object.assign(new Error("那台服务器上已经有了"), {
    status: 409,
    body: JSON.stringify({ detail: { code: "exists", message: "那台服务器上已经有了", suggestion } }),
  });
}

async function more(name: string) {
  await openDetail(name);
  fireEvent.click(screen.getByRole("button", { name: "workflowMore" }));
  return screen.getByRole("menu", { name: "workflowMore" });
}

beforeEach(() => {
  window.localStorage.clear();
  for (const fn of [api.getWorkflowContent, api.copyWorkflow, api.renameWorkflow, api.trashWorkflow, api.restoreWorkflow, saved,
                    api.createWorkflowFolder, api.renameWorkflowFolder, api.trashWorkflowFolder])
    fn.mockReset();
  window.location.hash = "#/plugins";
  api.getWorkflowLibrary.mockReset();
  api.getWorkflowLibrary.mockResolvedValue(library());
  handoff.mockReset();
  api.refreshPluginInstance.mockReset();
  api.refreshPluginInstance.mockResolvedValue({});
  for (const fn of [api.startNodeInstall, api.rebootWorkflowServer, api.getJob]) fn.mockReset();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView ??= () => {};
});

afterEach(() => {
  resetWorkbench();
  vi.unstubAllGlobals();
});

const EDITOR = { kind: "comfyui", url: "http://192.168.3.15:8188" };

type ViewState = { visible: boolean; accountId: string | null; accountName: string | null; partition?: string | null };

/** 桌面版的两座桥:开工作台的那一个,和内嵌视图亮出 / 收起的通知。 */
function desktop(result: { ok: boolean; outcome?: string; error?: string }) {
  const listeners = new Set<(state: ViewState) => void>();
  const openComfyWorkbench = vi.fn().mockResolvedValue(result);
  vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
  vi.stubGlobal("mosaelPublish", {
    onViewState: (callback: (state: ViewState) => void) => {
      listeners.add(callback);
      return () => listeners.delete(callback);
    },
  });
  const emit = (state: ViewState) => act(() => listeners.forEach((listener) => listener(state)));
  return { openComfyWorkbench, emit };
}

describe("工作流库", () => {
  it("左边一列:全部、文件夹(按名字排),钉在底部的「缺节点或模型」;一张卡一个节点图缩略预览", async () => {
    await openLibrary();
    expect(api.getWorkflowLibrary).toHaveBeenCalledWith("i1", "w1");
    const column = screen.getByRole("tablist", { name: "workflowLibraryFolders" });
    expect(within(column).getAllByRole("tab").map((tab) => tab.getAttribute("aria-label"))).toEqual([
      "workflowLibraryAll 3", "sub 1", "video 1", "workflowLibraryProblems 2",
    ]);
    expect(names()).toEqual(["portrait", "sketch", "wan"]);
    const portrait = cards()[0];
    const svg = portrait.querySelector("svg[data-workflow-graph]") as SVGElement;
    expect(svg.querySelectorAll("[data-graph-node]")).toHaveLength(3);
    expect(svg.querySelectorAll("[data-graph-link]")).toHaveLength(2);
    expect(svg.querySelector("[data-graph-node][data-muted]")).toBeTruthy();
    expect(portrait.textContent).toContain("workflowKind_image");
    const sketch = cards()[1];
    expect(sketch.textContent).toContain("workflowLibraryMissingNodes");

    fireEvent.click(folderTab("workflowLibraryProblems 2"));
    expect(names()).toEqual(["portrait", "sketch"]);
    fireEvent.click(folderTab("video 1"));
    expect(names()).toEqual(["wan"]);
  });

  it("搜索、按种类筛、排序;列表一行一张", async () => {
    await openLibrary();
    fireEvent.change(screen.getByRole("textbox", { name: "workflowLibrarySearch" }), { target: { value: "CR Prompt" } });
    expect(names()).toEqual(["sketch"]);
    fireEvent.change(screen.getByRole("textbox", { name: "workflowLibrarySearch" }), { target: { value: "" } });
    fireEvent.keyDown(screen.getByRole("combobox", { name: "workflowLibraryKind" }), { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "workflowKind_video" }));
    expect(names()).toEqual(["wan"]);
    fireEvent.keyDown(screen.getByRole("combobox", { name: "workflowLibraryKind" }), { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "workflowLibraryKindAll" }));
    fireEvent.keyDown(screen.getByRole("combobox", { name: "workflowLibrarySort" }), { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "workflowLibrarySortNodes" }));
    expect(names()).toEqual(["sketch", "wan", "portrait"]);

    fireEvent.click(screen.getByRole("radio", { name: "libraryDensityList" }));
    const table = screen.getByRole("table", { name: "workflowLibraryTitle" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getAllByRole("cell")[1].textContent)).toEqual(["sketch", "wan", "portrait"]);
    expect(window.localStorage.getItem("mosael:tab:workflow-library.density")).toBe("list");
  });

  it("详情:能填什么、参数、交出什么、用到的模型在不在、缺的模型、最近的产出、谁在用它(点了跳过去)", async () => {
    const back = await openDetail("portrait");
    const head = back.closest("[data-library-detail-head]") as HTMLElement;
    expect(within(head).getByRole("heading", { name: "portrait" })).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "workflowInputs" })).getByText("LoadImage")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "workflowParameters" })).getByText("步数")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "workflowOutputs" })).getByText("保存图像")).toBeTruthy();
    const usedModels = screen.getByRole("region", { name: "workflowModels" });
    expect(within(usedModels).getByText("sdxl.safetensors").closest("li")?.textContent).toContain("workflowModelPresent");
    expect(within(usedModels).getByText("gone.safetensors").closest("li")?.textContent).toContain("workflowModelMissing");
    const last = screen.getByRole("region", { name: "workflowLastOutput" });
    expect(within(last).getByRole("img").getAttribute("src")).toBe("thumb://a1");
    //: 最近的产出点开看大图(问过素材才知道是图还是视频,视频在灯箱里换成播放器)。
    fireEvent.click(await within(last).findByRole("button", { name: "viewFullSizeOf" }));
    expect(openImagePreview).toHaveBeenCalledWith({ src: "preview://a1", title: "产出 a1" });
    const media = document.querySelector("[data-library-detail-pane='media'] svg[data-workflow-graph]");
    expect(media).toBeTruthy();
    expect(media?.textContent).toContain("Load Checkpoint");

    const used = screen.getByRole("region", { name: "workflowUsedBy" });
    fireEvent.click(within(used).getByRole("button", { name: "出图流程" }));
    expect(window.location.hash).toBe("#/workflows?workflow=w1");
  });

  it("缺的节点:出自哪个节点包、装没装(装了却没加载的另说)", async () => {
    await openDetail("sketch");
    expect(screen.getByRole("alert").textContent).toContain("CR Prompt Text");
    const missing = screen.getByRole("region", { name: "workflowMissingNodes" });
    const cr = within(missing).getByText("CR Prompt Text").closest("li") as HTMLElement;
    expect(cr.textContent).toContain("Comfyroll Studio");
    expect(cr.textContent).toContain("×2");
    const rg = within(missing).getByText("Display Any (rgthree)").closest("li") as HTMLElement;
    expect(rg.textContent).toContain("workflowPackInstalledNotLoaded");
  });

  it("用它生成:交给 AI 工作台选中这张工作流;不是生成模型的点不了", async () => {
    await openDetail("portrait");
    fireEvent.click(screen.getByRole("button", { name: /modelUseToGenerate/ }));
    expect(handoff).toHaveBeenCalledWith({ providerProfileId: "p9", kind: "image", model: "portrait.json", declared: {},
                                           promptWords: [] });
    fireEvent.click(screen.getByRole("button", { name: "workflowLibraryBack" }));
    const card = (await screen.findAllByRole("listitem")).find((item) => item.textContent?.includes("sketch"))!;
    fireEvent.click(within(card).getByRole("button", { name: "sketch" }));
    await screen.findByRole("button", { name: "workflowLibraryBack" });
    expect((screen.getByRole("button", { name: /modelUseToGenerate/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("复制:先确认、写明是在哪台服务器上新建哪个文件;撞名不覆盖,给建议名", async () => {
    api.copyWorkflow.mockRejectedValueOnce(conflict("portrait (2).json")).mockResolvedValueOnce({ path: "portrait (2).json" });
    const menu = await more("portrait");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "workflowCopy" }));
    const dialog = await screen.findByRole("dialog", { name: "workflowCopyTitle" });
    expect(dialog.textContent).toContain("workflowWriteWhere");
    const input = within(dialog).getByRole("textbox", { name: "workflowPathLabel" }) as HTMLInputElement;
    expect(input.value).toBe("portrait (1).json");
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowCopyConfirm" }));
    await waitFor(() => expect(api.copyWorkflow).toHaveBeenCalledWith("i1", "portrait.json", "portrait (1).json"));
    const clash = await within(dialog).findByRole("alert");
    expect(clash.textContent).toContain("workflowExists");
    fireEvent.click(within(clash).getByRole("button"));
    expect(input.value).toBe("portrait (2).json");
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowCopyConfirm" }));
    await waitFor(() => expect(api.copyWorkflow).toHaveBeenLastCalledWith("i1", "portrait.json", "portrait (2).json"));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "workflowCopyTitle" })).toBeNull());
    expect(api.getWorkflowLibrary).toHaveBeenCalledTimes(2);
  });

  it("改名:名字不合格当场说,不发出去;.json 不用自己写", async () => {
    api.renameWorkflow.mockResolvedValue({ path: "人像/portrait.json" });
    const menu = await more("portrait");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "workflowRename" }));
    const dialog = await screen.findByRole("dialog", { name: "workflowRenameTitle" });
    const input = within(dialog).getByRole("textbox", { name: "workflowPathLabel" });
    fireEvent.change(input, { target: { value: "../出去" } });
    expect(within(dialog).getByText("workflowPathBad")).toBeTruthy();
    expect((within(dialog).getByRole("button", { name: "workflowRenameConfirm" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(input, { target: { value: "人像/portrait" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowRenameConfirm" }));
    await waitFor(() => expect(api.renameWorkflow).toHaveBeenCalledWith("i1", "portrait.json", "人像/portrait.json"));
  });

  it("删除:确认框说清楚是挪进回收站、Mosael 里谁在用它;确认后回到列表", async () => {
    api.trashWorkflow.mockResolvedValue({ path: ".mosael-trash/workflows/20261005-101500/portrait.json" });
    const menu = await more("portrait");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "workflowDelete" }));
    const confirm = await screen.findByRole("alertdialog");
    expect(confirm.textContent).toContain("workflowDeleteBody");
    expect(confirm.textContent).toContain("出图流程");
    expect(confirm.textContent).toContain("分镜板");
    fireEvent.click(within(confirm).getByRole("button", { name: "workflowDeleteConfirm" }));
    await waitFor(() => expect(api.trashWorkflow).toHaveBeenCalledWith("i1", "portrait.json"));
    expect(await screen.findByRole("list", { name: "workflowLibraryTitle" })).toBeTruthy();
  });

  it("导出 JSON:取原文下载到本机,不碰那台机器", async () => {
    api.getWorkflowContent.mockResolvedValue({ path: "portrait.json", content: { nodes: [], links: [] } });
    const menu = await more("portrait");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "workflowExport" }));
    await waitFor(() => expect(saved).toHaveBeenCalledWith("portrait.json", { nodes: [], links: [] }));
    expect(api.copyWorkflow).not.toHaveBeenCalled();
  });

  it("回收站:列出删了的,恢复也先确认;原处被占了就换个名字", async () => {
    api.getWorkflowLibrary.mockResolvedValue(library({
      trash: [{ path: ".mosael-trash/workflows/20261005-101500/old/one.json", original: "old/one.json", label: "one",
                deleted_at: 1791000000 }],
    }));
    api.restoreWorkflow.mockRejectedValueOnce(conflict("old/one (1).json")).mockResolvedValueOnce({ path: "old/one (1).json" });
    await openLibrary();
    fireEvent.click(folderTab("workflowLibraryTrash 1"));
    const trash = screen.getByRole("list", { name: "workflowLibraryTrash" });
    const row = within(trash).getByText("one").closest("li") as HTMLElement;
    expect(row.textContent).toContain("old/one.json");
    fireEvent.click(within(row).getByRole("button", { name: "workflowRestore" }));
    const dialog = await screen.findByRole("dialog", { name: "workflowRestoreTitle" });
    expect((within(dialog).getByRole("textbox", { name: "workflowPathLabel" }) as HTMLInputElement).value).toBe("old/one.json");
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowRestoreConfirm" }));
    await waitFor(() => expect(api.restoreWorkflow).toHaveBeenCalledWith("i1", ".mosael-trash/workflows/20261005-101500/old/one.json",
                                                                          "old/one.json"));
    fireEvent.click(within(await within(dialog).findByRole("alert")).getByRole("button"));
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowRestoreConfirm" }));
    await waitFor(() => expect(api.restoreWorkflow).toHaveBeenLastCalledWith("i1",
      ".mosael-trash/workflows/20261005-101500/old/one.json", "old/one (1).json"));
  });

  it("桌面版只有「在工作台里打开」:开的是工作台、打开这一张;没有不带面板的另一个入口;回到 Mosael 时刷新", async () => {
    //: 维护者:「应该仅仅一个工作台就够了吧」—— 此前桌面版详情头上并排两个,开的是同一个画布,一个带面板一个不带
    api.getWorkflowLibrary.mockResolvedValue(library({ editor: EDITOR }));
    const bridge = desktop({ ok: true, outcome: "opened" });
    await openDetail("portrait");
    expect(screen.getAllByRole("button", { name: /^workflowOpenIn/ }).map((one) => one.textContent), "只有一个打开的入口")
      .toEqual(["workflowOpenInWorkbench"]);
    fireEvent.click(screen.getByRole("button", { name: "workflowOpenInWorkbench" }));
    await waitFor(() => expect(bridge.openComfyWorkbench).toHaveBeenCalledWith({
      connectionId: "i1", url: EDITOR.url, name: instance.name, path: "portrait.json",
    }));
    const partition = "persist:pool-comfyui-i1";
    bridge.emit({ visible: true, accountId: partition, accountName: instance.name, partition });
    expect(api.refreshPluginInstance).not.toHaveBeenCalled();
    bridge.emit({ visible: false, accountId: null, accountName: null });
    await waitFor(() => expect(api.refreshPluginInstance).toHaveBeenCalledWith("i1"));
    await waitFor(() => expect(api.getWorkflowLibrary).toHaveBeenCalledTimes(2));
    bridge.emit({ visible: true, accountId: "persist:pool-other", accountName: "别的", partition: "persist:pool-other" });
    bridge.emit({ visible: false, accountId: null, accountName: null });
    expect(api.refreshPluginInstance, "只在自己开的那个视图收起时刷新一次").toHaveBeenCalledTimes(1);
  });

  it("在工作台里点了浏览器顶栏、在地址栏按了 Esc,回到 Mosael 时工作流库还开着、还停在那一张,照样刷新", async () => {
    const uninstall = installAppChromeGuards(document);
    try {
      api.getWorkflowLibrary.mockResolvedValue(library({ editor: EDITOR }));
      const bridge = desktop({ ok: true, outcome: "opened" });
      await openDetail("portrait");
      // 内嵌视图亮着时盖在最上层的顶栏(窗口外壳)。
      const bar = document.createElement("div");
      bar.setAttribute("data-app-chrome", "");
      bar.innerHTML = '<button type="button">返回 Mosael</button><input aria-label="地址栏" />';
      document.body.appendChild(bar);
      fireEvent.click(screen.getByRole("button", { name: "workflowOpenInWorkbench" }));
      await waitFor(() => expect(bridge.openComfyWorkbench).toHaveBeenCalled());
      const partition = "persist:pool-comfyui-i1";
      bridge.emit({ visible: true, accountId: partition, accountName: instance.name, partition });
      const address = bar.querySelector("input")!;
      fireEvent.pointerDown(address);
      act(() => address.focus());
      fireEvent.keyDown(address, { key: "Escape" });
      fireEvent.pointerDown(bar.querySelector("button")!);
      fireEvent.click(bar.querySelector("button")!);
      bridge.emit({ visible: false, accountId: null, accountName: null });
      bar.remove();
      await waitFor(() => expect(api.refreshPluginInstance).toHaveBeenCalledWith("i1"));
      expect(screen.getByRole("dialog")).toBeTruthy();
      expect(screen.getByRole("button", { name: "workflowLibraryBack" })).toBeTruthy();
      expect(screen.getByRole("button", { name: "workflowOpenInWorkbench" })).toBeTruthy();
    } finally {
      uninstall();
    }
  });

  it("工作台开的时候(要等本机服务起来、页面就绪)按钮转圈,不只是变灰;开好了停", async () => {
    api.getWorkflowLibrary.mockResolvedValue(library({ editor: EDITOR }));
    const bridge = desktop({ ok: true, outcome: "opened" });
    let opened: (value: unknown) => void = () => undefined;
    bridge.openComfyWorkbench.mockReturnValueOnce(new Promise((resolve) => { opened = resolve; }));
    await openDetail("portrait");
    const open = () => screen.getByRole("button", { name: "workflowOpenInWorkbench" });
    fireEvent.click(open());
    await waitFor(() => expect(open().getAttribute("aria-busy")).toBe("true"));
    expect(open().querySelector("svg.animate-mosael-spin")).not.toBeNull();
    await act(async () => opened({ ok: true, outcome: "opened" }));
    await waitFor(() => expect(open().getAttribute("aria-busy")).toBeNull());
    expect((open() as HTMLButtonElement).disabled).toBe(false);
  });

  it("在工作台里打开:那台机器上没找到这一张、或者没打开成,回来时看得到怎么办", async () => {
    api.getWorkflowLibrary.mockResolvedValue(library({ editor: EDITOR }));
    const bridge = desktop({ ok: true, outcome: "missing" });
    await openDetail("portrait");
    fireEvent.click(screen.getByRole("button", { name: "workflowOpenInWorkbench" }));
    expect((await screen.findByRole("status")).textContent).toContain("workflowEditorMissing");
    bridge.openComfyWorkbench.mockResolvedValueOnce({ ok: false, error: "前台正被另一个页面占着" });
    fireEvent.click(screen.getByRole("button", { name: "workflowOpenInWorkbench" }));
    expect((await screen.findByRole("alert")).textContent).toContain("前台正被另一个页面占着");
  });

  it("网页版只有「在 ComfyUI 里打开」:新标签页开这台 ComfyUI,说清楚在左边「工作流」里点开哪一张;回到这个标签页时刷新", async () => {
    api.getWorkflowLibrary.mockResolvedValue(library({ editor: EDITOR }));
    const opened = vi.fn(() => null);
    vi.stubGlobal("open", opened);
    await openDetail("portrait");
    expect(screen.getAllByRole("button", { name: /^workflowOpenIn/ }).map((one) => one.textContent), "网页版没有工作台,也只有一个")
      .toEqual(["workflowOpenInComfy"]);
    fireEvent.click(screen.getByRole("button", { name: "workflowOpenInComfy" }));
    expect(opened).toHaveBeenCalledWith(EDITOR.url, "_blank", "noopener,noreferrer");
    expect((await screen.findByRole("status")).textContent).toContain("workflowEditorTab");
    fireEvent.focus(window);
    await waitFor(() => expect(api.refreshPluginInstance).toHaveBeenCalledWith("i1"));
  });

  it("插件没给编辑器地址就没有打开的按钮", async () => {
    await openDetail("portrait");
    expect(screen.queryByRole("button", { name: /^workflowOpenIn/ })).toBeNull();
  });

  it("新建(桌面版):工具条上和「导入」并排;在工作台里新建一张,回到 Mosael 时刷新", async () => {
    api.getWorkflowLibrary.mockResolvedValue(library({ editor: EDITOR }));
    const bridge = desktop({ ok: true, outcome: "created" });
    await openLibrary();
    const create = screen.getByRole("button", { name: "workflowNew" });
    const imports = screen.getByRole("button", { name: "workflowImport" });
    expect(create.compareDocumentPosition(imports) & Node.DOCUMENT_POSITION_FOLLOWING, "新建排在导入前面").toBeTruthy();
    fireEvent.click(create);
    await waitFor(() => expect(bridge.openComfyWorkbench).toHaveBeenCalledWith({
      connectionId: "i1", url: EDITOR.url, name: instance.name, fresh: true,
    }));
    const partition = "persist:pool-comfyui-i1";
    bridge.emit({ visible: true, accountId: partition, accountName: instance.name, partition });
    expect(api.refreshPluginInstance).not.toHaveBeenCalled();
    // 在 ComfyUI 里存了一张新的,回来:目录重拉、工作流库重新列 —— 新的那张出现在列表里
    api.getWorkflowLibrary.mockResolvedValue(library({ editor: EDITOR, workflows: [...(library().workflows ?? []), flow({ path: "新的.json", label: "新的" })] }));
    bridge.emit({ visible: false, accountId: null, accountName: null });
    await waitFor(() => expect(api.refreshPluginInstance).toHaveBeenCalledWith("i1"));
    await waitFor(() => expect(names()).toContain("新的"));
    expect(screen.queryByRole("status"), "新建成了不留话").toBeNull();
  });

  it("新建(桌面版):工作台开的时候「新建」转圈;卡片菜单里打开的那一项这期间点不了", async () => {
    api.getWorkflowLibrary.mockResolvedValue(library({ editor: EDITOR }));
    const bridge = desktop({ ok: true, outcome: "created" });
    let created: (value: unknown) => void = () => undefined;
    bridge.openComfyWorkbench.mockReturnValueOnce(new Promise((resolve) => { created = resolve; }));
    await openLibrary();
    const create = () => screen.getByRole("button", { name: "workflowNew" });
    fireEvent.click(create());
    await waitFor(() => expect(create().getAttribute("aria-busy")).toBe("true"));
    fireEvent.contextMenu(cardOf("portrait"));
    expect(menuRows(await screen.findByRole("menu"))).toContain("workflowOpenInWorkbench(禁用)");
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    await act(async () => created({ ok: true, outcome: "created" }));
    await waitFor(() => expect(create().getAttribute("aria-busy")).toBeNull());
  });

  it("新建:这版 ComfyUI 前端没有「新建」命令就说清楚(画布照样开着,自己点),回来时照样刷新", async () => {
    api.getWorkflowLibrary.mockResolvedValue(library({ editor: EDITOR }));
    const bridge = desktop({ ok: true, outcome: "unsupported" });
    await openLibrary();
    fireEvent.click(screen.getByRole("button", { name: "workflowNew" }));
    expect((await screen.findByRole("status")).textContent).toContain("workflowNewUnsupported");
    const partition = "persist:pool-comfyui-i1";
    bridge.emit({ visible: true, accountId: partition, accountName: instance.name, partition });
    bridge.emit({ visible: false, accountId: null, accountName: null });
    await waitFor(() => expect(api.refreshPluginInstance).toHaveBeenCalledWith("i1"));
    bridge.openComfyWorkbench.mockResolvedValueOnce({ ok: false, error: "前台正被另一个页面占着" });
    fireEvent.click(screen.getByRole("button", { name: "workflowNew" }));
    expect((await screen.findByRole("alert")).textContent).toContain("前台正被另一个页面占着");
  });

  it("新建(网页版):新标签页开这台 ComfyUI,说在那边点「新建」;回到这个标签页时刷新", async () => {
    api.getWorkflowLibrary.mockResolvedValue(library({ editor: EDITOR }));
    const opened = vi.fn(() => null);
    vi.stubGlobal("open", opened);
    await openLibrary();
    fireEvent.click(screen.getByRole("button", { name: "workflowNew" }));
    expect(opened).toHaveBeenCalledWith(EDITOR.url, "_blank", "noopener,noreferrer");
    expect((await screen.findByRole("status")).textContent).toContain("workflowNewTab");
    fireEvent.focus(window);
    await waitFor(() => expect(api.refreshPluginInstance).toHaveBeenCalledWith("i1"));
  });

  it("插件没给编辑器地址就没有「新建」;一张都没有时空状态里也给「新建」", async () => {
    await openLibrary();
    expect(screen.queryByRole("button", { name: "workflowNew" })).toBeNull();
    api.getWorkflowLibrary.mockResolvedValue(library({ editor: EDITOR, workflows: [] }));
    wrap(<WorkflowLibraryDialog open onOpenChange={() => undefined} instance={instance} workspaceId="w2" />);
    await screen.findByText("workflowLibraryEmpty");
    expect(screen.getAllByRole("button", { name: "workflowNew" }).length).toBeGreaterThanOrEqual(2);
  });

  it("用到的模型:在的点了跳到模型库那一项;缺的模型点了去模型库下载(带上工作流里写的地址)", async () => {
    const showModel = vi.fn();
    wrap(<WorkflowLibraryDialog open onOpenChange={() => undefined} instance={instance} workspaceId="w1" onShowModel={showModel} />);
    const card = (await screen.findAllByRole("listitem")).find((item) => item.textContent?.includes("portrait"))!;
    fireEvent.click(within(card).getByRole("button", { name: "portrait" }));
    const usedModels = await screen.findByRole("region", { name: "workflowModels" });
    const present = within(usedModels).getByText("sdxl.safetensors").closest("li") as HTMLElement;
    fireEvent.click(within(present).getByRole("button", { name: "workflowShowInModelLibrary" }));
    expect(showModel).toHaveBeenLastCalledWith({ model: { folder: "checkpoints", name: "sdxl.safetensors" } });
    const absent = within(usedModels).getByText("gone.safetensors").closest("li") as HTMLElement;
    expect(within(absent).queryByRole("button"), "缺的在「缺的模型」那一节里下载").toBeNull();
    //: 两行一样高、徽章对成一列:按钮是 32px 的方按钮,缺的那行在同一位置留一格一样大的空位
    expect(within(present).getByRole("button", { name: "workflowShowInModelLibrary" }).className).toContain("size-8");
    expect(absent.querySelector("[data-model-row-slot]")?.className).toContain("size-8");
    for (const row of [present, absent]) expect(row.className).toContain("min-h-8");
    const missing = screen.getByRole("region", { name: "workflowMissingModels" });
    fireEvent.click(within(missing).getByRole("button", { name: "workflowDownloadInModelLibrary" }));
    expect(showModel).toHaveBeenLastCalledWith({
      download: { folder: "loras", name: "gone.safetensors", url: "https://huggingface.co/x/y/resolve/main/gone.safetensors" },
    });
  });

  it("不能跳去模型库(连接没认领模型库)就只列名字", async () => {
    await openDetail("portrait");
    const usedModels = screen.getByRole("region", { name: "workflowModels" });
    expect(within(usedModels).queryByRole("button")).toBeNull();
  });

  it("从模型库跳过来:停到那一张", async () => {
    wrap(<WorkflowLibraryDialog open onOpenChange={() => undefined} instance={instance} workspaceId="w1"
                                focus={{ path: "video/wan.json", at: 1 }} />);
    await screen.findByRole("button", { name: "workflowLibraryBack" });
    expect(screen.getByRole("heading", { name: "wan" })).toBeTruthy();
  });

  it("缺的节点:没装的节点包能「装上」—— 先确认;装好了给「重启 ComfyUI」,也先确认;重启完重新列", async () => {
    const job = { id: "j1", kind: "node_install", status: "running", progress: 0.4, message: "正在装", error: "",
                  result: null, updated_at: "2020-01-01T00:00:00Z",
                  payload: { packs: ["ComfyUI_Comfyroll_CustomNodes"], subject: "ComfyUI_Comfyroll_CustomNodes" } };
    api.startNodeInstall.mockResolvedValue(job);
    api.getJob.mockResolvedValue({ ...job, status: "succeeded", progress: 1,
                                   result: { installed: ["ComfyUI_Comfyroll_CustomNodes"], restart: true } });
    api.rebootWorkflowServer.mockResolvedValue({ back: true });
    await openDetail("sketch");
    const missing = screen.getByRole("region", { name: "workflowMissingNodes" });
    const installs = within(missing).getAllByRole("button", { name: "workflowInstallPackLabel" });
    expect(installs, "装了却没加载的那个包不给「装上」").toHaveLength(1);
    fireEvent.click(installs[0]);
    const ask = await screen.findByRole("alertdialog");
    expect(ask.textContent).toContain("workflowInstallBody");
    fireEvent.click(within(ask).getByRole("button", { name: "workflowInstallConfirm" }));
    await waitFor(() => expect(api.startNodeInstall).toHaveBeenCalledWith("i1", {
      workspace_id: "w1", packs: ["ComfyUI_Comfyroll_CustomNodes"],
    }));
    await waitFor(() => expect(within(missing).getByText(/workflowInstallDone/)).toBeTruthy(), { timeout: 4000 });
    fireEvent.click(within(missing).getByRole("button", { name: "workflowRestart" }));
    const restart = await screen.findByRole("alertdialog");
    expect(restart.textContent).toContain("workflowRestartBody");
    const before = api.getWorkflowLibrary.mock.calls.length;
    // 重启回来:这个包装上了,可这台(假的)ComfyUI 还是没加载它
    const reloaded = library();
    reloaded.workflows![2].missing_nodes![0].packs![0].installed = true;
    api.getWorkflowLibrary.mockResolvedValue(reloaded);
    fireEvent.click(within(restart).getByRole("button", { name: "workflowRestartConfirm" }));
    await waitFor(() => expect(api.rebootWorkflowServer).toHaveBeenCalledWith("i1"));
    await waitFor(() => expect(api.getWorkflowLibrary.mock.calls.length).toBeGreaterThan(before));
    const after = await screen.findByRole("region", { name: "workflowMissingNodes" });
    await waitFor(() => expect(after.textContent).toContain("workflowInstalledNotLoaded"));
    expect(after.textContent, "重启过了:不再说「重启之后才加载」").not.toContain("workflowInstallDone");
  });

  it("装节点包没装成:原话留着", async () => {
    const job = { id: "j2", kind: "node_install", status: "running", progress: 0.1, message: "", error: "", result: null,
                  payload: { packs: ["ComfyUI_Comfyroll_CustomNodes"], subject: "ComfyUI_Comfyroll_CustomNodes" } };
    api.startNodeInstall.mockResolvedValue(job);
    api.getJob.mockResolvedValue({ ...job, status: "failed", error: "ComfyUI-Manager 不让经网络装节点包:network_mode 改成 personal_cloud" });
    await openDetail("sketch");
    const missing = screen.getByRole("region", { name: "workflowMissingNodes" });
    fireEvent.click(within(missing).getByRole("button", { name: "workflowInstallPackLabel" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "workflowInstallConfirm" }));
    await waitFor(() => expect(missing.textContent).toContain("personal_cloud"), { timeout: 4000 });
  });

  it("装了却没加载的节点包:给「重启 ComfyUI」", async () => {
    await openDetail("sketch");
    const missing = screen.getByRole("region", { name: "workflowMissingNodes" });
    expect(missing.textContent).toContain("workflowInstalledNotLoaded");
    expect(within(missing).getByRole("button", { name: "workflowRestart" })).toBeTruthy();
  });

  it("没装 ComfyUI-Manager:不给「装上」,说在那台机器上手动装", async () => {
    api.getWorkflowLibrary.mockResolvedValue(library({ manager: { version: "" } }));
    await openDetail("sketch");
    const missing = screen.getByRole("region", { name: "workflowMissingNodes" });
    expect(within(missing).queryByRole("button", { name: "workflowInstallPackLabel" })).toBeNull();
    expect(missing.textContent).toContain("workflowInstallNoManager");
  });

  it("读不出来:居中说清楚、能重试", async () => {
    api.getWorkflowLibrary.mockRejectedValueOnce(new Error("连不上这台 ComfyUI,确认它在运行、地址填对\nhttp://x:[Errno 61]"));
    wrap(<ConnectionLibraries instance={instance} workspaceId="w1" workflows />);
    fireEvent.click(screen.getByRole("button", { name: "workflowLibraryOpen" }));
    const title = await screen.findByText("workflowLibraryErrorTitle");
    expect(title.closest(".empty-state")?.textContent).not.toContain("Errno");
    fireEvent.click(screen.getByRole("button", { name: "retry" }));
    await waitFor(() => expect(api.getWorkflowLibrary).toHaveBeenCalledTimes(2));
  });
});

/** 那台机器上的文件夹:video 下面一个空的「草稿」,顶上一个空的「空的」;sub 只从工作流的路径推出来。 */
const WITH_FOLDERS = () => library({ folders: ["video", "video/草稿", "空的"] });

const column = () => screen.getByRole("tablist", { name: "workflowLibraryFolders" });
const tabNames = () => within(column()).getAllByRole("tab").map((tab) => tab.getAttribute("aria-label"));
const cardOf = (name: string) => cards().find((item) => item.querySelector("[data-library-open]")?.textContent === name)!
  .querySelector("article") as HTMLElement;
/** 菜单里一条条摆着什么:分组线记成 `|`,点不了的后面带 `(禁用)`。只看名字那一行,不连说明。 */
function menuRows(menu: HTMLElement): string[] {
  return Array.from(menu.querySelectorAll<HTMLElement>("[role=menuitem], [role=separator]")).map((one) => {
    if (one.getAttribute("role") === "separator") return "|";
    const name = one.querySelector("[data-menu-icon] + span > :first-child")?.textContent ?? one.textContent ?? "";
    const disabled = one.hasAttribute("data-disabled") || (one as HTMLButtonElement).disabled;
    return disabled ? `${name}(禁用)` : name;
  });
}
/** 拖放带的数据:jsdom 没有 DataTransfer,用一个够用的。 */
function transfer() {
  const data = new Map<string, string>();
  return {
    setData: (type: string, value: string) => void data.set(type, value),
    getData: (type: string) => data.get(type) ?? "",
    get types() { return [...data.keys()]; },
    effectAllowed: "", dropEffect: "",
  };
}

describe("工作流库 · 文件夹", () => {
  it("文件夹树:按名字排、子文件夹缩进、空的也在、数量连同子文件夹;选一个只看它和它下面的,搜索框说在哪、几张", async () => {
    api.getWorkflowLibrary.mockResolvedValue(library({
      folders: ["video", "video/草稿", "空的"],
      workflows: [...library().workflows!, flow({ path: "video/草稿/old.json", label: "old", folder: "video/草稿", kind: "video" })],
    }));
    await openLibrary();
    expect(tabNames()).toEqual([
      "workflowLibraryAll 4", "sub 1", "video 2", "video/草稿 1", "空的 0", "workflowLibraryProblems 2",
    ]);
    const nested = folderTab("video/草稿 1");
    expect(nested.textContent).toContain("草稿");
    expect(nested.textContent, "树里只写最后一段,全名给读屏").not.toContain("video/");
    expect(nested.style.paddingInlineStart, "子文件夹往里缩一格").toBe("24px");
    fireEvent.click(folderTab("video 2"));
    expect(names(), "选 video:它和它下面的").toEqual(["old", "wan"]);
    expect(screen.getByRole("textbox", { name: "workflowLibrarySearchIn" }).getAttribute("placeholder")).toBe("workflowLibrarySearchIn");
    fireEvent.change(screen.getByRole("textbox", { name: "workflowLibrarySearchIn" }), { target: { value: "wan" } });
    expect(names(), "搜索在选中的文件夹里搜").toEqual(["wan"]);
    fireEvent.click(folderTab("video/草稿 1"));
    expect(screen.getByText("workflowLibraryNoMatchTitle"), "草稿里没有叫 wan 的").toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "workflowLibrarySearchIn" }), { target: { value: "" } });
    expect(names()).toEqual(["old"]);
  });

  it("新建文件夹:左栏顶上的按钮,建在选中的文件夹里;先确认、写明改哪台机器;撞名不合并,给建议名;建好停到它", async () => {
    api.getWorkflowLibrary.mockResolvedValue(WITH_FOLDERS());
    api.createWorkflowFolder
      .mockRejectedValueOnce(conflict("video/workflowFolderDefaultName (1)"))
      .mockResolvedValueOnce({ path: "video/workflowFolderDefaultName (1)" });
    await openLibrary();
    fireEvent.click(folderTab("video 1"));
    const button = screen.getByRole("button", { name: "workflowFolderNew" });
    expect(column().contains(button), "按钮不在页签组里").toBe(false);
    fireEvent.click(button);
    const dialog = await screen.findByRole("dialog", { name: "workflowFolderNewTitle" });
    expect(dialog.textContent).toContain("workflowFolderWhere");
    const input = within(dialog).getByRole("textbox", { name: "workflowFolderPathLabel" }) as HTMLInputElement;
    expect(input.value).toBe("video/workflowFolderDefaultName");
    fireEvent.change(input, { target: { value: "video/x.json" } });
    expect(within(dialog).getByText("workflowFolderPathBad")).toBeTruthy();
    expect((within(dialog).getByRole("button", { name: "workflowFolderNewConfirm" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(input, { target: { value: "video/workflowFolderDefaultName" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowFolderNewConfirm" }));
    await waitFor(() => expect(api.createWorkflowFolder).toHaveBeenCalledWith("i1", "video/workflowFolderDefaultName"));
    const clash = await within(dialog).findByRole("alert");
    api.getWorkflowLibrary.mockResolvedValue(library({ folders: ["video", "video/草稿", "video/workflowFolderDefaultName (1)", "空的"] }));
    fireEvent.click(within(clash).getByRole("button"));
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowFolderNewConfirm" }));
    await waitFor(() => expect(api.createWorkflowFolder).toHaveBeenLastCalledWith("i1", "video/workflowFolderDefaultName (1)"));
    await waitFor(() => expect(folderTab("video/workflowFolderDefaultName (1) 0").getAttribute("aria-selected")).toBe("true"));
  });

  it("文件夹的右键菜单(⋯、Shift+F10 也是它):新建子文件夹、改名、删除;里面有文件的删不了,说为什么", async () => {
    api.getWorkflowLibrary.mockResolvedValue(WITH_FOLDERS());
    await openLibrary();
    fireEvent.contextMenu(folderTab("video 1"));
    const menu = await screen.findByRole("menu");
    expect(menuRows(menu)).toEqual(["workflowFolderNewInside", "workflowFolderRename", "|", "workflowFolderDelete(禁用)"]);
    expect(within(menu).getByText("workflowFolderDeleteNotEmpty"), "点不了的写着为什么").toBeTruthy();
    fireEvent.keyDown(menu, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    fireEvent.keyDown(folderTab("空的 0"), { key: "F10", shiftKey: true });
    const keyboard = await screen.findByRole("menu");
    expect(menuRows(keyboard)).toEqual(["workflowFolderNewInside", "workflowFolderRename", "|", "workflowFolderDelete"]);
    fireEvent.keyDown(keyboard, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    fireEvent.click(folderTab("空的 0"));
    const more = within(folderTab("空的 0").parentElement!).getByRole("button", { name: "workflowFolderActions" });
    expect(more.tabIndex, "选中的那一项的 ⋯ 进 Tab 顺序").toBe(0);
    expect(within(folderTab("video 1").parentElement!).getByRole("button", { name: "workflowFolderActions" }).tabIndex).toBe(-1);
    fireEvent.click(more);
    expect(menuRows(screen.getByRole("menu", { name: "workflowFolderActions" })))
      .toEqual(["workflowFolderNewInside", "workflowFolderRename", "|", "workflowFolderDelete"]);
  });

  it("文件夹改名:里面几张跟着换路径要说;改成了停到新名字", async () => {
    api.getWorkflowLibrary.mockResolvedValue(WITH_FOLDERS());
    api.renameWorkflowFolder.mockResolvedValue({ path: "视频" });
    await openLibrary();
    fireEvent.click(folderTab("video 1"));
    fireEvent.contextMenu(folderTab("video 1"));
    fireEvent.click(within(await screen.findByRole("menu")).getByRole("menuitem", { name: "workflowFolderRename" }));
    const dialog = await screen.findByRole("dialog", { name: "workflowFolderRenameTitle" });
    expect(dialog.textContent).toContain("workflowFolderRenameNote");
    const input = within(dialog).getByRole("textbox", { name: "workflowFolderPathLabel" });
    expect((input as HTMLInputElement).value).toBe("video");
    api.getWorkflowLibrary.mockResolvedValue(library({
      folders: ["视频", "视频/草稿", "空的"],
      workflows: library().workflows!.map((one) => one.path === "video/wan.json" ? { ...one, path: "视频/wan.json", folder: "视频" } : one),
    }));
    fireEvent.change(input, { target: { value: "视频" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowFolderRenameConfirm" }));
    await waitFor(() => expect(api.renameWorkflowFolder).toHaveBeenCalledWith("i1", "video", "视频"));
    await waitFor(() => expect(folderTab("视频 1").getAttribute("aria-selected")).toBe("true"));
  });

  it("删除文件夹:空的才能删,先确认(挪进回收目录);这期间里面有了东西,照后端说的说、不关", async () => {
    api.getWorkflowLibrary.mockResolvedValue(WITH_FOLDERS());
    api.trashWorkflowFolder.mockRejectedValueOnce(Object.assign(new Error("不空"), {
      status: 409, body: JSON.stringify({ detail: { code: "not_empty", message: "不空", count: 2 } }),
    })).mockResolvedValueOnce({ path: ".mosael-trash/workflows/20261006-010000/空的" });
    await openLibrary();
    fireEvent.contextMenu(folderTab("空的 0"));
    fireEvent.click(within(await screen.findByRole("menu")).getByRole("menuitem", { name: "workflowFolderDelete" }));
    const dialog = await screen.findByRole("dialog", { name: "workflowFolderDeleteTitle" });
    expect(dialog.textContent).toContain("workflowFolderDeleteBody");
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowFolderDeleteConfirm" }));
    await waitFor(() => expect(api.trashWorkflowFolder).toHaveBeenCalledWith("i1", "空的"));
    expect((await within(dialog).findByRole("alert")).textContent).toBe("workflowFolderNotEmptyNow");
    expect(api.getWorkflowLibrary.mock.calls.length, "没删成也重新列:手里这份旧了").toBe(2);
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowFolderDeleteConfirm" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "workflowFolderDeleteTitle" })).toBeNull());
    expect(api.trashWorkflowFolder).toHaveBeenCalledTimes(2);
  });

  it("把卡片拖到左边的文件夹上:打开「移动」确认框,那个文件夹已经选好;确认后改路径", async () => {
    api.getWorkflowLibrary.mockResolvedValue(WITH_FOLDERS());
    api.renameWorkflow.mockResolvedValue({ path: "video/草稿/portrait.json" });
    await openLibrary();
    const data = transfer();
    fireEvent.dragStart(cardOf("portrait"), { dataTransfer: data });
    expect(data.getData("application/x-mosael-workflow")).toBe("portrait.json");
    const target = folderTab("video/草稿 0");
    fireEvent.dragOver(target, { dataTransfer: data });
    expect(target.closest("[data-drop-target]"), "拖到上面时亮起来").toBeTruthy();
    fireEvent.drop(target, { dataTransfer: data });
    const dialog = await screen.findByRole("dialog", { name: "workflowMoveTitle" });
    expect((within(dialog).getByRole("radio", { name: /草稿/ }) as HTMLInputElement).checked).toBe(true);
    expect(dialog.textContent).toContain("workflowMoveUsedBy");
    expect(dialog.textContent, "portrait 在 Mosael 里有人在用:说一声").toContain("出图流程");
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowMoveConfirm" }));
    await waitFor(() => expect(api.renameWorkflow).toHaveBeenCalledWith("i1", "portrait.json", "video/草稿/portrait.json"));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "workflowMoveTitle" })).toBeNull());
  });

  it("拖到它本来就在的文件夹上、拖进来的不是卡片(是文件):不动", async () => {
    api.getWorkflowLibrary.mockResolvedValue(WITH_FOLDERS());
    await openLibrary();
    const data = transfer();
    fireEvent.dragStart(cardOf("portrait"), { dataTransfer: data });
    fireEvent.drop(folderTab("workflowLibraryAll 3"), { dataTransfer: data });
    const files = { types: ["Files"], getData: () => "", files: [] };
    fireEvent.dragOver(folderTab("video 1"), { dataTransfer: files });
    expect(folderTab("video 1").closest("[data-drop-target]")).toBeNull();
    expect(screen.queryByRole("dialog", { name: "workflowMoveTitle" })).toBeNull();
  });
});

describe("工作流库 · 卡片的菜单", () => {
  const CARD_MENU = [
    "workflowMenuOpen", "workflowOpenInComfy(禁用)", "|",
    "workflowMenuEditApp(禁用)", "|",
    "workflowCopy", "workflowRename", "workflowMove", "workflowExport", "|",
    "workflowCopyPath", "|",
    "workflowMenuMissingModels", "|",
    "workflowDelete",
  ];

  it("右键、⋯、Shift+F10 / 菜单键打开的是同一份菜单,分好组;点不了的写着为什么;只有缺东西的才有「补齐」那一组", async () => {
    await openLibrary();
    fireEvent.contextMenu(cardOf("portrait"));
    const byMouse = await screen.findByRole("menu");
    expect(menuRows(byMouse)).toEqual(CARD_MENU);
    for (const why of ["workflowMenuNoEditor", "workflowMenuAppUnavailable"]) expect(within(byMouse).getAllByText(why).length).toBeGreaterThan(0);
    fireEvent.keyDown(byMouse, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());

    fireEvent.click(within(cardOf("portrait")).getByRole("button", { name: "workflowActions" }));
    expect(menuRows(screen.getByRole("menu", { name: "workflowActions" }))).toEqual(CARD_MENU);
    fireEvent.keyDown(screen.getByRole("menu", { name: "workflowActions" }), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());

    const open = within(cardOf("portrait")).getByRole("button", { name: "portrait" });
    open.focus();
    fireEvent.keyDown(open, { key: "F10", shiftKey: true });
    expect(menuRows(await screen.findByRole("menu"))).toEqual(CARD_MENU);
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    fireEvent.keyDown(within(cardOf("wan")).getByRole("button", { name: "wan" }), { key: "ContextMenu" });
    expect(menuRows(await screen.findByRole("menu")), "什么都不缺:没有「补齐」那一组").not.toContain("workflowMenuMissingModels");
  });

  it("有编辑器、有应用表单时都点得开;缺节点的给「装缺的节点」", async () => {
    api.getWorkflowLibrary.mockResolvedValue(library({
      editor: EDITOR,
      workflows: library().workflows!.map((one) => one.path === "sub/sketch.json"
        ? { ...one, app: { status: "ok", version: "1", app: false, title: "", description: "", items: [], results: [], invalid: 0, fields: 0 } }
        : one),
    }));
    await openLibrary();
    fireEvent.contextMenu(cardOf("sketch"));
    const rows = menuRows(await screen.findByRole("menu"));
    expect(rows.slice(0, 4), "网页版:只有「在 ComfyUI 里打开」").toEqual(["workflowMenuOpen", "workflowOpenInComfy", "|", "workflowMenuEditApp"]);
    expect(rows).toContain("workflowMenuMissingNodes");
    fireEvent.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: /workflowMenuEditApp/ }));
    expect(await screen.findByRole("dialog", { name: /workflowApp/ })).toBeTruthy();
  });

  it("「移动到…」:挑一个文件夹,名字不变;目标里有同名的不覆盖,给建议名", async () => {
    api.getWorkflowLibrary.mockResolvedValue(WITH_FOLDERS());
    api.renameWorkflow.mockRejectedValueOnce(conflict("空的/wan (1).json")).mockResolvedValueOnce({ path: "空的/wan (1).json" });
    await openLibrary();
    fireEvent.contextMenu(cardOf("wan"));
    fireEvent.click(within(await screen.findByRole("menu")).getByRole("menuitem", { name: "workflowMove" }));
    const dialog = await screen.findByRole("dialog", { name: "workflowMoveTitle" });
    const here = within(dialog).getByRole("radio", { name: /^video/ }) as HTMLInputElement;
    expect(here.checked, "停在它现在所在的文件夹").toBe(true);
    const confirm = within(dialog).getByRole("button", { name: "workflowMoveConfirm" }) as HTMLButtonElement;
    expect(confirm.disabled, "没换地方点不了").toBe(true);
    fireEvent.click(within(dialog).getByRole("radio", { name: /空的/ }));
    expect(dialog.textContent).toContain("workflowMoveResult");
    fireEvent.click(confirm);
    await waitFor(() => expect(api.renameWorkflow).toHaveBeenCalledWith("i1", "video/wan.json", "空的/wan.json"));
    fireEvent.click(within(await within(dialog).findByRole("alert")).getByRole("button"));
    fireEvent.click(confirm);
    await waitFor(() => expect(api.renameWorkflow).toHaveBeenLastCalledWith("i1", "video/wan.json", "空的/wan (1).json"));
    //: 改了名,模型下拉里它也该换名:后端存着的这个连接的目录要重拉,不只是让界面重问
    await waitFor(() => expect(api.refreshPluginInstance).toHaveBeenCalledWith("i1"));
  });

  it("复制路径、导出 JSON、删除从菜单里也能做;在列表上改名不跳进详情", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    api.getWorkflowContent.mockResolvedValue({ path: "portrait.json", content: { nodes: [] } });
    api.renameWorkflow.mockResolvedValue({ path: "人像.json" });
    await openLibrary();
    const pick = async (name: string) => {
      fireEvent.contextMenu(cardOf("portrait"));
      fireEvent.click(within(await screen.findByRole("menu")).getByRole("menuitem", { name: new RegExp(`^${name}`) }));
    };
    await pick("workflowCopyPath");
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("portrait.json"));
    await pick("workflowExport");
    await waitFor(() => expect(saved).toHaveBeenCalledWith("portrait.json", { nodes: [] }));
    await pick("workflowRename");
    const dialog = await screen.findByRole("dialog", { name: "workflowRenameTitle" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "workflowPathLabel" }), { target: { value: "人像" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowRenameConfirm" }));
    await waitFor(() => expect(api.renameWorkflow).toHaveBeenCalledWith("i1", "portrait.json", "人像.json"));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "workflowRenameTitle" })).toBeNull());
    expect(screen.queryByRole("button", { name: "workflowLibraryBack" }), "留在列表上").toBeNull();
    await pick("workflowDelete");
    expect((await screen.findByRole("alertdialog")).textContent).toContain("workflowDeleteBody");
  });

  it("「下载缺的模型」「装缺的节点」:打开详情,停到那一节", async () => {
    await openLibrary();
    fireEvent.contextMenu(cardOf("portrait"));
    fireEvent.click(within(await screen.findByRole("menu")).getByRole("menuitem", { name: "workflowMenuMissingModels" }));
    await screen.findByRole("button", { name: "workflowLibraryBack" });
    const models = screen.getByRole("region", { name: "workflowMissingModels" });
    await waitFor(() => expect(document.activeElement).toBe(models.querySelector("h4")));
    fireEvent.click(screen.getByRole("button", { name: "workflowLibraryBack" }));
    await screen.findByRole("list", { name: "workflowLibraryTitle" });
    fireEvent.contextMenu(cardOf("sketch"));
    fireEvent.click(within(await screen.findByRole("menu")).getByRole("menuitem", { name: "workflowMenuMissingNodes" }));
    const nodes = await screen.findByRole("region", { name: "workflowMissingNodes" });
    await waitFor(() => expect(document.activeElement).toBe(nodes.querySelector("h4")));
  });

  it("列表的一行:右键、行尾的 ⋯ 一样的菜单;也能拖", async () => {
    api.getWorkflowLibrary.mockResolvedValue(WITH_FOLDERS());
    await openLibrary();
    fireEvent.click(screen.getByRole("radio", { name: "libraryDensityList" }));
    const row = within(screen.getByRole("table", { name: "workflowLibraryTitle" })).getAllByRole("row")
      .find((one) => one.textContent?.includes("portrait"))!;
    fireEvent.contextMenu(row);
    expect(menuRows(await screen.findByRole("menu"))).toEqual(CARD_MENU);
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    fireEvent.click(within(row).getByRole("button", { name: "workflowActions" }));
    expect(screen.queryByRole("button", { name: "workflowLibraryBack" }), "点 ⋯ 不打开这一行").toBeNull();
    fireEvent.click(within(screen.getByRole("menu", { name: "workflowActions" })).getByRole("menuitem", { name: "workflowMove" }));
    expect(await screen.findByRole("dialog", { name: "workflowMoveTitle" })).toBeTruthy();
    const data = transfer();
    fireEvent.dragStart(row, { dataTransfer: data });
    expect(data.getData("application/x-mosael-workflow")).toBe("portrait.json");
  });
});
