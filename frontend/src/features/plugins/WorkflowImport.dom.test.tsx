/** @vitest-environment jsdom */

/**
 * 工作流库的「导入」(ADR 0035 §5):拖进来 / 选文件 / 贴 JSON 或链接 → 先让插件认一遍,看预览 → 存进那台服务器。
 *
 * - 文件以 base64 带着文件名交;贴的是链接就按链接交,别的按文字交;
 * - 预览写明从哪儿认出来的、什么格式(API 格式说位置是自动排的)、插件要说的话、节点图、能填什么、缺的节点和模型;
 * - 路径默认是插件建议的那个,没给就界面自己给一个不撞名的;撞名(409)不覆盖、给建议名;存好回到库里、打开那一张;
 * - 认不出就当场说原话,能换一个再认;
 * - 往工作流库上拖文件,直接打开导入并认那个文件。
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
  refreshPluginInstance: vi.fn(),
  inspectWorkflowImport: vi.fn(),
  saveImportedWorkflow: vi.fn(),
  assetThumbnailUrl: (id: string) => `thumb://${id}`,
}));
vi.mock("@/api/client", () => api);
vi.mock("@/lib/download", () => ({ saveJsonToDisk: vi.fn() }));
vi.mock("@/lib/generationHandoff", () => ({ handOffToGeneration: vi.fn() }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh" }),
}));

import type { PluginInstance, WorkflowImport, WorkflowLibrary } from "@/api/client";
import { WorkflowLibraryDialog } from "./WorkflowLibrary";

const instance = { id: "i1", name: "ComfyUI · 192.168.3.15", blocked_reason: "" } as PluginInstance;
const UI_FLOW = { id: "new-id", nodes: [{ id: 3, type: "KSampler" }], links: [] };

function library(paths: string[] = ["portrait.json"]): WorkflowLibrary {
  return {
    workflows: paths.map((path) => ({
      path, label: path.replace(/\.json$/, ""), folder: "", size: 1, modified: 1, kind: "image", problem: "", node_count: 1,
      graph: { nodes: [], links: [], groups: [], auto_layout: false, truncated: false },
      inputs: [], parameters: [], outputs: [], models: [], missing_nodes: [], missing_models: [],
      generation: null, last_output: null, used_by: [],
    })),
    others: [], trash: [], manager: { version: "V4.2.1" }, editor: null,
  } as WorkflowLibrary;
}

function preview(overrides: Partial<WorkflowImport> = {}): WorkflowImport {
  return {
    format: "api", source: "png", workflow: UI_FLOW, suggested_path: "人像.json",
    notes: ["这份是 API 格式,没有布局"], kind: "image", problem: "", node_count: 7,
    graph: { nodes: [{ x: 0, y: 0, w: 320, h: 200, role: "sampler", muted: false, title: "KSampler" }], links: [], groups: [],
             auto_layout: true, truncated: false },
    inputs: [{ node: "10", title: "参考图", media: "image", role: "reference_image" }],
    parameters: [{ key: "3.steps", title: "步数", type: "integer" }],
    outputs: [{ node: "9", title: "保存", media: "image" }],
    models: [{ folder: "checkpoints", name: "sdxl.safetensors", present: true }],
    missing_nodes: [{ type: "CR Prompt Text", count: 1, packs: [{ id: "ComfyUI_Comfyroll_CustomNodes", title: "Comfyroll", installed: false }] }],
    missing_models: [{ folder: "loras", name: "x.safetensors", url: "https://huggingface.co/a/b/resolve/main/x.safetensors" }],
    ...overrides,
  } as WorkflowImport;
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(node, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
}

async function openLibrary() {
  wrap(<WorkflowLibraryDialog open onOpenChange={() => undefined} instance={instance} workspaceId="w1" />);
  await screen.findByRole("list", { name: "workflowLibraryTitle" });
}

async function openImport() {
  await openLibrary();
  fireEvent.click(screen.getByRole("button", { name: /workflowImport$/ }));
  return await screen.findByRole("dialog", { name: "workflowImportTitle" });
}

/** 一个会被 FileReader 读成 base64 的文件。 */
function file(name: string, content: string, type = "") {
  return new File([content], name, { type });
}

beforeEach(() => {
  for (const fn of Object.values(api)) if (typeof fn === "function" && "mockReset" in fn) fn.mockReset();
  api.getWorkflowLibrary.mockResolvedValue(library());
  api.refreshPluginInstance.mockResolvedValue({});
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView ??= () => {};
});

describe("导入工作流", () => {
  it("贴一段 JSON → 认一下 → 预览 → 存进那台服务器 → 回到库里打开那一张", async () => {
    api.inspectWorkflowImport.mockResolvedValue(preview({ source: "json" }));
    api.saveImportedWorkflow.mockResolvedValue({ path: "人像.json" });
    const dialog = await openImport();
    fireEvent.change(within(dialog).getByRole("textbox", { name: "workflowImportPasteLabel" }), {
      target: { value: '{"3": {"class_type": "KSampler", "inputs": {}}}' },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowImportInspect" }));
    await waitFor(() => expect(api.inspectWorkflowImport).toHaveBeenCalledWith("i1", { text: '{"3": {"class_type": "KSampler", "inputs": {}}}' }));
    expect(await within(dialog).findByText("workflowImportSource_json")).toBeTruthy();
    expect(dialog.textContent).toContain("workflowImportFormat_api");
    expect(dialog.textContent).toContain("这份是 API 格式,没有布局");
    expect(within(dialog).getByRole("img", { name: /workflowGraphLabel/ })).toBeTruthy();
    expect(within(dialog).getByRole("region", { name: "workflowMissingNodes" }).textContent).toContain("CR Prompt Text");
    expect(within(dialog).getByRole("region", { name: "workflowMissingModels" }).textContent).toContain("x.safetensors");
    expect(within(dialog).queryByRole("button", { name: /workflowDownloadInModelLibrary/ }), "还没存进去:不给下载").toBeNull();
    expect(dialog.textContent).toContain("workflowWriteWhere");
    const path = within(dialog).getByRole("textbox", { name: "workflowPathLabel" }) as HTMLInputElement;
    expect(path.value).toBe("人像.json");
    api.getWorkflowLibrary.mockResolvedValue(library(["portrait.json", "人像.json"]));
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowImportConfirm" }));
    await waitFor(() => expect(api.saveImportedWorkflow).toHaveBeenCalledWith("i1", "人像.json", UI_FLOW));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "workflowImportTitle" })).toBeNull());
    expect(await screen.findByRole("heading", { name: "人像" })).toBeTruthy();
  });

  it("选文件:以 base64 带着文件名交给插件", async () => {
    api.inspectWorkflowImport.mockResolvedValue(preview());
    const dialog = await openImport();
    const input = dialog.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file("ComfyUI_00012_.png", "PNGDATA", "image/png")] } });
    await waitFor(() => expect(api.inspectWorkflowImport).toHaveBeenCalledWith("i1", {
      data: btoa("PNGDATA"), filename: "ComfyUI_00012_.png",
    }));
    expect(await within(dialog).findByText("workflowImportSource_png")).toBeTruthy();
  });

  it("贴的是链接就按链接交", async () => {
    api.inspectWorkflowImport.mockResolvedValue(preview({ source: "url" }));
    const dialog = await openImport();
    fireEvent.change(within(dialog).getByRole("textbox", { name: "workflowImportPasteLabel" }), {
      target: { value: "  https://huggingface.co/a/b/resolve/main/flow.json  " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowImportInspect" }));
    await waitFor(() => expect(api.inspectWorkflowImport).toHaveBeenCalledWith("i1", {
      url: "https://huggingface.co/a/b/resolve/main/flow.json",
    }));
  });

  it("认不出:当场说原话,换一个再认", async () => {
    api.inspectWorkflowImport.mockRejectedValueOnce(new Error("认不出这是一张 ComfyUI 工作流"));
    const dialog = await openImport();
    fireEvent.change(within(dialog).getByRole("textbox", { name: "workflowImportPasteLabel" }), { target: { value: "随便" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowImportInspect" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("认不出这是一张 ComfyUI 工作流");
    expect(within(dialog).getByRole("textbox", { name: "workflowImportPasteLabel" })).toBeTruthy();
  });

  it("撞名不覆盖:给建议名;插件没给建议路径时界面自己给一个不撞名的", async () => {
    api.inspectWorkflowImport.mockResolvedValue(preview({ suggested_path: "" }));
    api.saveImportedWorkflow
      .mockRejectedValueOnce(Object.assign(new Error("exists"), {
        status: 409, body: JSON.stringify({ detail: { code: "exists", message: "exists", suggestion: "workflowImportDefaultName (2).json" } }),
      }))
      .mockResolvedValueOnce({ path: "workflowImportDefaultName (2).json" });
    api.getWorkflowLibrary.mockResolvedValue(library(["workflowImportDefaultName.json"]));
    const dialog = await openImport();
    fireEvent.change(within(dialog).getByRole("textbox", { name: "workflowImportPasteLabel" }), { target: { value: "{}" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowImportInspect" }));
    const path = (await within(dialog).findByRole("textbox", { name: "workflowPathLabel" })) as HTMLInputElement;
    expect(path.value).toBe("workflowImportDefaultName (1).json");
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowImportConfirm" }));
    const clash = await within(dialog).findByRole("alert");
    fireEvent.click(within(clash).getByRole("button"));
    expect(path.value).toBe("workflowImportDefaultName (2).json");
    fireEvent.click(within(dialog).getByRole("button", { name: "workflowImportConfirm" }));
    await waitFor(() => expect(api.saveImportedWorkflow).toHaveBeenLastCalledWith("i1", "workflowImportDefaultName (2).json", UI_FLOW));
  });

  it("往工作流库上拖文件:直接打开导入并认那个文件", async () => {
    api.inspectWorkflowImport.mockResolvedValue(preview());
    await openLibrary();
    const target = screen.getByRole("dialog", { name: "workflowLibraryTitle" });
    const dropped = file("flow.json", "{}", "application/json");
    const dataTransfer = { types: ["Files"], files: [dropped], items: [{ kind: "file", type: "application/json" }], dropEffect: "" };
    fireEvent.dragEnter(target, { dataTransfer });
    fireEvent.dragOver(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });
    const dialog = await screen.findByRole("dialog", { name: "workflowImportTitle" });
    await waitFor(() => expect(api.inspectWorkflowImport).toHaveBeenCalledWith("i1", { data: btoa("{}"), filename: "flow.json" }));
    expect(await within(dialog).findByText("workflowImportSource_png")).toBeTruthy();
  });
});
