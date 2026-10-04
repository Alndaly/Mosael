/** @vitest-environment jsdom */

/**
 * 工作流库(ADR 0035):一个连接那台服务器上存着的工作流,和模型库同一套骨架(LibraryBrowser)。数据是
 * `/workflow-library` 给的,这里看的是怎么摆:
 *
 * - 左边一列子目录(按数量排),钉在底部的「缺节点或模型」;顶上搜索、按种类筛、排序、三档显示方式;
 * - 一张卡:节点图缩略预览(照图摘要画成 SVG)、名字、种类、节点数、缺什么;
 * - 点开是详情:能填什么 / 参数 / 交出什么、用到的模型(在不在)、缺的节点(出自哪个节点包、装没装)和缺的模型、
 *   最近的产出、Mosael 里谁在用它(点了跳过去);「用它生成」交给 AI 工作台,不是生成模型的点不了并说为什么;
 * - 改那台机器上的文件(复制、改名、删除、恢复)每次都先确认、写明改哪台服务器的哪个文件;撞名(409)不覆盖,给建议名;
 *   删除是挪进回收目录,确认框里说清楚 Mosael 里谁在用它;「回收站」里能恢复;导出 JSON 只是下载到本机。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getWorkflowLibrary: vi.fn(),
  getWorkflowContent: vi.fn(),
  copyWorkflow: vi.fn(),
  renameWorkflow: vi.fn(),
  trashWorkflow: vi.fn(),
  restoreWorkflow: vi.fn(),
  assetThumbnailUrl: (id: string) => `thumb://${id}`,
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
import { WorkflowLibraryButton } from "./WorkflowLibrary";

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
  wrap(<WorkflowLibraryButton instance={instance} workspaceId="w1" />);
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
  for (const fn of [api.getWorkflowContent, api.copyWorkflow, api.renameWorkflow, api.trashWorkflow, api.restoreWorkflow, saved])
    fn.mockReset();
  window.location.hash = "#/plugins";
  api.getWorkflowLibrary.mockReset();
  api.getWorkflowLibrary.mockResolvedValue(library());
  handoff.mockReset();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView ??= () => {};
});

describe("工作流库", () => {
  it("左边一列:全部、子目录(按数量排),钉在底部的「缺节点或模型」;一张卡一个节点图缩略预览", async () => {
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

  it("读不出来:居中说清楚、能重试", async () => {
    api.getWorkflowLibrary.mockRejectedValueOnce(new Error("连不上这台 ComfyUI,确认它在运行、地址填对\nhttp://x:[Errno 61]"));
    wrap(<WorkflowLibraryButton instance={instance} workspaceId="w1" />);
    fireEvent.click(screen.getByRole("button", { name: "workflowLibraryOpen" }));
    const title = await screen.findByText("workflowLibraryErrorTitle");
    expect(title.closest(".empty-state")?.textContent).not.toContain("Errno");
    fireEvent.click(screen.getByRole("button", { name: "retry" }));
    await waitFor(() => expect(api.getWorkflowLibrary).toHaveBeenCalledTimes(2));
  });
});
