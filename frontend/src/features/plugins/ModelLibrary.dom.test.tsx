/** @vitest-environment jsdom */

/**
 * 模型库(ADR 0034):一个连接那台服务器上的模型文件。不认识任何一家插件 —— 数据是 `/model-library` 给的,这里看的是
 * 怎么摆、怎么下:
 *
 * - 按目录分页签、搜索;有预览图用宿主的预览地址,没有就是按目录分的占位;
 * - 点开是详情:底模和凭的是什么、触发词(来自训练标签时说清楚)、在用的工作流、文件头里的元数据;
 * - 工作流缺的模型一键下载:下载框带着地址、目录、文件名,解析之后确认,发起的任务在模型库里看得到进度、能取消;
 * - 同名文件不覆盖:换一个名字(给建议)之前「下载」点不了;这台服务器下不了时也点不了,并说为什么。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getModelLibrary: vi.fn(),
  getModelDetail: vi.fn(),
  resolveModelLink: vi.fn(),
  startModelDownload: vi.fn(),
  getJob: vi.fn(),
  cancelJob: vi.fn(),
  modelPreviewUrl: (instance: string, folder: string, name: string) => `preview://${instance}/${folder}/${name}`,
}));
vi.mock("@/api/client", () => api);
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh" }),
}));

import type { Job, ModelLibrary, PluginInstance } from "@/api/client";
import { ModelLibraryRow, freeName } from "./ModelLibrary";

const instance = { id: "i1", name: "ComfyUI · 192.168.3.15", blocked_reason: "" } as PluginInstance;

function library(overrides: Partial<ModelLibrary> = {}): ModelLibrary {
  return {
    folders: [
      { name: "checkpoints", count: 2 },
      { name: "loras", count: 2 },
      { name: "vae", count: 0 },
    ],
    models: [
      { folder: "checkpoints", name: "sd_xl_base.safetensors", size: 6938041004, modified: 1700000000, family: "SDXL",
        family_source: "metadata", triggers: [], triggers_source: "", title: "", has_preview: false,
        used_by: [{ id: "portrait.json", label: "portrait" }] },
      { folder: "checkpoints", name: "AWPainting_IL.safetensors", size: 6938041004, modified: 1700000001,
        family: "Illustrious", family_source: "filename", triggers: [], triggers_source: "", title: "", has_preview: false,
        used_by: [] },
      { folder: "loras", name: "detail.safetensors", size: 228456516, modified: 1700000002, family: "Illustrious",
        family_source: "metadata", triggers: ["1girl", "solo"], triggers_source: "tags", title: "detail_tweaker",
        has_preview: true, used_by: [{ id: "declaring.json", label: "declaring" }] },
      { folder: "loras", name: "sub\\anima_style.safetensors", size: 1000, modified: 1700000003, family: "anima",
        family_source: "metadata", triggers: ["anima style"], triggers_source: "metadata", title: "", has_preview: false,
        used_by: [] },
    ],
    missing: [{ folder: "vae", name: "ae.safetensors", url: "https://huggingface.co/x/y/resolve/main/ae.safetensors",
                workflows: [{ id: "declaring.json", label: "declaring" }] }],
    download: { route: "local", note: "ComfyUI 就在这台电脑上" },
    downloads: [],
    ...overrides,
  };
}

function job(overrides: Partial<Job>): Job {
  return {
    id: "j1", workspace_id: "w1", kind: "model_download", parent_job_id: null, status: "running", progress: 0.4,
    message: "已下载 132 MB / 335 MB", payload: { instance_id: "i1", folder: "vae", filename: "ae.safetensors",
                                               url: "https://huggingface.co/x/y/resolve/main/ae.safetensors" },
    result: {}, error: null, created_at: "2026-10-04T12:00:00Z", updated_at: "2026-10-04T12:00:01Z",
    ...overrides,
  } as Job;
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(node, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
}

async function openLibrary() {
  wrap(<ModelLibraryRow instance={instance} workspaceId="w1" />);
  fireEvent.click(screen.getByRole("button", { name: "modelLibraryOpen" }));
  return within(await screen.findByRole("list", { name: "modelLibraryTitle" }));
}

beforeEach(() => {
  for (const fn of [api.getModelLibrary, api.getModelDetail, api.resolveModelLink, api.startModelDownload, api.getJob,
    api.cancelJob]) fn.mockReset();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  api.getModelLibrary.mockResolvedValue(library());
});

describe("模型库", () => {
  it("按目录分页签、搜索;有预览图用宿主的地址,没有就是按目录分的占位", async () => {
    const grid = await openLibrary();
    expect(api.getModelLibrary).toHaveBeenCalledWith("i1");
    expect(grid.getAllByRole("listitem")).toHaveLength(4);
    const tabs = screen.getByRole("group", { name: "modelLibraryFolders" });
    expect(within(tabs).queryByRole("button", { name: /vae/ })).toBeNull();
    fireEvent.click(within(tabs).getByRole("button", { name: "loras 2" }));
    expect(grid.getAllByRole("listitem")).toHaveLength(2);
    const detail = grid.getAllByRole("listitem").find((item) => item.textContent?.includes("detail.safetensors"))!;
    expect(within(detail).getByRole("img").getAttribute("src")).toBe("preview://i1/loras/detail.safetensors");
    const anima = grid.getAllByRole("listitem").find((item) => item.textContent?.includes("anima_style.safetensors"))!;
    expect(anima.querySelector("[data-placeholder='loras']")).toBeTruthy();
    expect(anima.textContent).toContain("loras/sub");
    fireEvent.click(within(tabs).getByRole("button", { name: "modelLibraryAll 4" }));
    fireEvent.change(screen.getByRole("textbox", { name: "modelLibrarySearch" }), { target: { value: "anima style" } });
    expect(grid.getAllByRole("listitem")).toHaveLength(1);
  });

  it("点开是详情:底模和凭的是什么、触发词来自训练标签时说清楚、在用的工作流、文件头里的元数据", async () => {
    api.getModelDetail.mockResolvedValue({ folder: "loras", name: "detail.safetensors",
                                           metadata: { ss_output_name: "detail_tweaker" }, tags: [{ tag: "1girl", count: 45 }] });
    const grid = await openLibrary();
    const card = grid.getAllByRole("listitem").find((item) => item.textContent?.includes("detail.safetensors"))!;
    fireEvent.click(within(card).getByRole("button", { name: "detail.safetensors" }));
    expect(await screen.findByText("detail_tweaker")).toBeTruthy();
    expect(api.getModelDetail).toHaveBeenCalledWith("i1", "loras", "detail.safetensors");
    expect(screen.getByText("modelTriggersFromTags")).toBeTruthy();
    expect(screen.getAllByText("modelFamilySourceMetadata").length).toBeGreaterThan(0);
    expect(screen.getByText("declaring")).toBeTruthy();
    expect(screen.getByText("ss_output_name")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "modelLibraryBack" }));
    expect(await screen.findByRole("list", { name: "modelLibraryTitle" })).toBeTruthy();
  });

  it("工作流缺的模型一键下载:带着地址、目录、文件名解析,确认后任务在模型库里看得到进度、能取消", async () => {
    api.resolveModelLink.mockResolvedValue({ source: "huggingface", url: "https://huggingface.co/x/y/resolve/main/ae.safetensors",
      page: "", filename: "ae.safetensors", size: 335304388, folder: "vae", family: "", triggers: [], title: "",
      exists: false, suggested_filename: "", note: "" });
    api.startModelDownload.mockResolvedValue(job({ status: "queued", progress: 0, message: "排队" }));
    api.getJob.mockResolvedValue(job({}));
    api.cancelJob.mockResolvedValue(job({ status: "failed" }));
    await openLibrary();
    const missing = screen.getByRole("region", { name: "modelMissingTitle" });
    expect(missing.textContent).toContain("ae.safetensors");
    fireEvent.click(within(missing).getByRole("button", { name: /modelMissingDownload/ }));
    await waitFor(() => expect(api.resolveModelLink).toHaveBeenCalledWith("i1", "https://huggingface.co/x/y/resolve/main/ae.safetensors"));
    const confirm = await screen.findByRole("button", { name: /modelDownloadConfirm/ });
    await waitFor(() => expect((confirm as HTMLButtonElement).disabled).toBe(false));
    expect(screen.getByText(/modelDownloadDiskLocal/)).toBeTruthy();
    fireEvent.click(confirm);
    await waitFor(() => expect(api.startModelDownload).toHaveBeenCalledWith("i1", {
      workspace_id: "w1", url: "https://huggingface.co/x/y/resolve/main/ae.safetensors", folder: "vae", filename: "ae.safetensors",
    }));
    const downloads = await screen.findByRole("region", { name: "modelDownloadsTitle" });
    await waitFor(() => expect(downloads.textContent).toContain("已下载 132 MB / 335 MB"));
    expect(within(downloads).getByRole("progressbar")).toBeTruthy();
    fireEvent.click(within(downloads).getByRole("button", { name: "modelDownloadCancelLabel" }));
    await waitFor(() => expect(api.cancelJob).toHaveBeenCalled());
    expect(api.cancelJob.mock.calls[0][0]).toBe("j1");
  });

  it("下好了让模型库重新列一遍", async () => {
    api.getModelLibrary.mockResolvedValueOnce(library({ downloads: [job({})] }));
    api.getJob.mockResolvedValue(job({ status: "succeeded", progress: 1, message: "ae.safetensors 已下到 vae" }));
    await openLibrary();
    await waitFor(() => expect(api.getModelLibrary).toHaveBeenCalledTimes(2), { timeout: 4000 });
  });

  it("同名文件不覆盖:换名之前点不了下载,给一个不撞名的建议", async () => {
    api.resolveModelLink.mockResolvedValue({ source: "civitai", url: "https://civitai.com/api/download/models/5",
      page: "", filename: "detail.safetensors", size: 1024, folder: "loras", family: "SDXL", triggers: [], title: "D · v1",
      exists: true, suggested_filename: "detail (1).safetensors", note: "" });
    await openLibrary();
    fireEvent.click(screen.getByRole("button", { name: /modelLibraryDownload/ }));
    const link = await screen.findByPlaceholderText("modelDownloadLinkPlaceholder");
    fireEvent.change(link, { target: { value: "https://civitai.com/models/4?modelVersionId=5" } });
    fireEvent.click(screen.getByRole("button", { name: "modelDownloadResolve" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("modelDownloadExists");
    const confirm = screen.getByRole("button", { name: /modelDownloadConfirm/ }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.click(within(alert).getByRole("button"));
    expect((screen.getByDisplayValue("detail (1).safetensors") as HTMLInputElement).value).toBe("detail (1).safetensors");
    expect(confirm.disabled).toBe(false);
  });

  it("这台服务器下不了:说为什么,点不了下载", async () => {
    api.getModelLibrary.mockResolvedValue(library({ download: { route: "none", note: "在那台机器上装 ComfyUI-Manager" } }));
    api.resolveModelLink.mockResolvedValue({ source: "direct", url: "https://example.com/x.safetensors", page: "",
      filename: "x.safetensors", size: null, folder: "", family: "", triggers: [], title: "", exists: false,
      suggested_filename: "", note: "" });
    await openLibrary();
    const missing = screen.getByRole("region", { name: "modelMissingTitle" });
    fireEvent.click(within(missing).getByRole("button", { name: /modelMissingDownload/ }));
    expect(await screen.findByText(/在那台机器上装 ComfyUI-Manager/)).toBeTruthy();
    expect(screen.getByText("modelDownloadCannot")).toBeTruthy();
    expect((screen.getByRole("button", { name: /modelDownloadConfirm/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("不撞名的建议和插件同一个规矩", () => {
    const taken = new Set(["a.safetensors", "a (1).safetensors"]);
    expect(freeName("a.safetensors", taken)).toBe("a (2).safetensors");
    expect(freeName("noext", new Set(["noext"]))).toBe("noext (1)");
  });
});

