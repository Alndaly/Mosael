/** @vitest-environment jsdom */

/**
 * 模型库(ADR 0034):一个连接那台服务器上的模型文件。不认识任何一家插件 —— 数据是 `/model-library` 给的,这里看的是
 * 怎么摆、怎么下:
 *
 * - 左边一列目录(按数量排、空的不列,缺的模型和下载记录是钉在底部的特殊项),上下方向键切换,窄窗口收成下拉;
 * - 顶上一条工具条:搜索(写着当前范围有几个)、按底模多选(只列当前目录里有的)、排序;生效的筛选一个个能去掉;
 * - 三档显示方式(大卡片 / 小卡片 / 列表),记在本机;
 * - 有预览图用宿主的预览地址,没有就是按目录分的占位;
 * - 点开是详情:底模和凭的是什么、触发词(来自训练标签时说清楚)、在用的工作流、文件头里的元数据;
 * - 工作流缺的模型一键下载:下载框带着地址、目录、文件名,解析之后确认,发起的任务在模型库里看得到进度、能取消;
 * - 同名文件不覆盖:换一个名字(给建议)之前「下载」点不了;这台服务器下不了时也点不了,并说为什么。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
import { ModelLibraryButton, freeName } from "./ModelLibrary";

const instance = { id: "i1", name: "ComfyUI · 192.168.3.15", blocked_reason: "" } as PluginInstance;

function library(overrides: Partial<ModelLibrary> = {}): ModelLibrary {
  return {
    folders: [
      { name: "checkpoints", count: 2 },
      { name: "loras", count: 3 },
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
      { folder: "loras", name: "pony_style.safetensors", size: 50000000, modified: 1700000010, family: "Pony",
        family_source: "filename", triggers: [], triggers_source: "", title: "", has_preview: false, used_by: [] },
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
  wrap(<ModelLibraryButton instance={instance} workspaceId="w1" />);
  fireEvent.click(screen.getByRole("button", { name: "modelLibraryOpen" }));
  return within(await screen.findByRole("list", { name: "modelLibraryTitle" }));
}

async function openLibraryAs(role: "list" | "table") {
  wrap(<ModelLibraryButton instance={instance} workspaceId="w1" />);
  fireEvent.click(screen.getByRole("button", { name: "modelLibraryOpen" }));
  return within(await screen.findByRole(role, { name: "modelLibraryTitle" }));
}

const cards = () => within(screen.getByRole("list", { name: "modelLibraryTitle" })).getAllByRole("listitem");
const names = () => cards().map((card) => card.querySelector("[data-library-open]")?.textContent);
const folderTab = (name: string) => within(screen.getByRole("tablist", { name: "modelLibraryFolders" })).getByRole("tab", { name });

function pickFamilies(...labels: string[]) {
  fireEvent.click(screen.getByRole("button", { name: /modelLibraryFamilyLabel/ }));
  const menu = screen.getByRole("menu", { name: "modelLibraryFamilyLabel" });
  for (const label of labels) fireEvent.click(within(menu).getByRole("menuitemcheckbox", { name: label }));
  return menu;
}

function narrowWindow() {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string) => ({
      matches: query.includes("max-width: 760px"), media: query, onchange: null,
      addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

const wideMatchMedia = window.matchMedia;

beforeEach(() => {
  window.localStorage.clear();
  Object.defineProperty(window, "matchMedia", { configurable: true, value: wideMatchMedia });
  Element.prototype.scrollIntoView ??= () => {};
  for (const fn of [api.getModelLibrary, api.getModelDetail, api.resolveModelLink, api.startModelDownload, api.getJob,
    api.cancelJob]) fn.mockReset();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  api.getModelLibrary.mockResolvedValue(library());
});

describe("模型库", () => {
  it("左边一列目录:按文件数排、空目录不列;最上面是「全部」,工作流缺的模型钉在底部;上下方向键切换", async () => {
    await openLibrary();
    expect(api.getModelLibrary).toHaveBeenCalledWith("i1");
    const column = screen.getByRole("tablist", { name: "modelLibraryFolders" });
    expect(column.getAttribute("aria-orientation")).toBe("vertical");
    expect(within(column).getAllByRole("tab").map((tab) => tab.getAttribute("aria-label"))).toEqual([
      "modelLibraryAll 5", "loras 3", "checkpoints 2", "modelMissingTitle 1",
    ]);
    const all = folderTab("modelLibraryAll 5");
    expect(all.getAttribute("aria-selected")).toBe("true");
    // 只有选中的那一项在 Tab 顺序里:Tab 一下就离开这一列,进工具条和网格
    expect(within(column).getAllByRole("tab").map((tab) => tab.tabIndex)).toEqual([0, -1, -1, -1]);
    expect(cards()).toHaveLength(5);

    fireEvent.keyDown(all, { key: "ArrowDown" });
    const loras = folderTab("loras 3");
    expect(loras.getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(document.activeElement).toBe(loras));
    expect(names()).toEqual(["anima_style.safetensors", "detail.safetensors", "pony_style.safetensors"]);
    // 搜索框写着当前范围有几个
    expect(screen.getByRole("textbox", { name: "modelLibrarySearchIn" })).toBeTruthy();

    fireEvent.keyDown(loras, { key: "End" });
    expect(await screen.findByRole("region", { name: "modelMissingTitle" })).toBeTruthy();
    expect(screen.queryByRole("list", { name: "modelLibraryTitle" })).toBeNull();
  });

  it("有预览图用宿主的地址,没有就是按目录分的占位;大卡片上写着目录和子目录", async () => {
    await openLibrary();
    fireEvent.click(screen.getByRole("radio", { name: "modelLibraryDensityLarge" }));
    fireEvent.click(folderTab("loras 3"));
    const detail = cards().find((item) => item.textContent?.includes("detail.safetensors"))!;
    expect(within(detail).getByRole("img").getAttribute("src")).toBe("preview://i1/loras/detail.safetensors");
    const anima = cards().find((item) => item.textContent?.includes("anima_style.safetensors"))!;
    expect(anima.querySelector("[data-placeholder='loras']")).toBeTruthy();
    expect(anima.textContent).toContain("loras/sub");
  });

  it("三档显示方式:默认小卡片;选了哪一档记在本机,下次打开还是它", async () => {
    await openLibrary();
    const group = screen.getByRole("radiogroup", { name: "modelLibraryDensity" });
    expect(within(group).getByRole("radio", { name: "modelLibraryDensitySmall" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("list", { name: "modelLibraryTitle" }).getAttribute("data-density")).toBe("small");
    fireEvent.click(within(group).getByRole("radio", { name: "modelLibraryDensityList" }));
    expect(screen.queryByRole("list", { name: "modelLibraryTitle" })).toBeNull();
    cleanup();

    await openLibraryAs("table");
    expect(screen.getByRole("radio", { name: "modelLibraryDensityList" }).getAttribute("aria-checked")).toBe("true");
  });

  it("列表:一行一个文件 —— 缩略图、名字、目录、底模、大小、改动时间、几张工作流在用;点名字看详情", async () => {
    window.localStorage.setItem("mosael:tab:model-library.density", "list");
    api.getModelDetail.mockResolvedValue({ folder: "checkpoints", name: "sd_xl_base.safetensors", metadata: {}, tags: [] });
    const table = await openLibraryAs("table");
    expect(table.getAllByRole("columnheader").map((one) => one.textContent)).toEqual([
      "modelLibraryColPreview", "modelFileName", "modelFolder", "modelFamily", "modelSize", "modelModified", "modelLibraryColUsed",
    ]);
    const rows = table.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(5);
    const sdxl = rows.find((row) => row.textContent?.includes("sd_xl_base.safetensors"))!;
    const cells = within(sdxl).getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells.slice(1, 5)).toEqual(["sd_xl_base.safetensors", "checkpoints", "SDXL", "6.9 GB"]);
    expect(cells[5]).toBeTruthy();
    expect(cells[6]).toBe("1");
    const anima = rows.find((row) => row.textContent?.includes("anima_style.safetensors"))!;
    expect(within(anima).getAllByRole("cell")[2].textContent).toBe("loras/sub");
    fireEvent.click(within(sdxl).getByRole("button", { name: "sd_xl_base.safetensors" }));
    expect(await screen.findByRole("button", { name: "modelLibraryBack" })).toBeTruthy();
  });

  it("底模只列当前目录里有的、带数量,可以勾几种(其中任一),勾的时候菜单不关", async () => {
    await openLibrary();
    fireEvent.click(screen.getByRole("button", { name: /modelLibraryFamilyLabel/ }));
    let menu = screen.getByRole("menu", { name: "modelLibraryFamilyLabel" });
    expect(within(menu).getAllByRole("menuitemcheckbox").map((item) => item.getAttribute("aria-label"))).toEqual([
      "Illustrious 2", "anima 1", "Pony 1", "SDXL 1",
    ]);
    fireEvent.keyDown(menu, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());

    fireEvent.click(folderTab("loras 3"));
    menu = pickFamilies("anima 1", "Pony 1");
    expect(within(menu).getAllByRole("menuitemcheckbox").map((item) => item.getAttribute("aria-label"))).toEqual([
      "anima 1", "Illustrious 1", "Pony 1",
    ]);
    expect(within(menu).getByRole("menuitemcheckbox", { name: "anima 1" }).getAttribute("aria-checked")).toBe("true");
    expect(names()).toEqual(["anima_style.safetensors", "pony_style.safetensors"]);

    // 换到一个没有这几种底模的目录:勾着的不再算数(否则网格莫名其妙是空的)
    fireEvent.keyDown(menu, { key: "Escape" });
    fireEvent.click(folderTab("checkpoints 2"));
    expect(cards()).toHaveLength(2);
    expect(screen.queryByRole("group", { name: "modelLibraryActiveFilters" })).toBeNull();
  });

  it("生效的筛选摆成一排:一个个去掉,或者一键清除;筛不出来时说清楚,能直接清除", async () => {
    await openLibrary();
    fireEvent.change(screen.getByRole("textbox", { name: "modelLibrarySearch" }), { target: { value: "style" } });
    const menu = pickFamilies("anima 1", "Illustrious 2");
    fireEvent.keyDown(menu, { key: "Escape" });
    const chips = screen.getByRole("group", { name: "modelLibraryActiveFilters" });
    expect(within(chips).getAllByRole("button").map((one) => one.getAttribute("aria-label") ?? one.textContent)).toEqual([
      "modelLibraryChipRemoveSearch", "modelLibraryChipRemoveFamily", "modelLibraryChipRemoveFamily", "libraryClearAll",
    ]);
    expect(names()).toEqual(["anima_style.safetensors"]);

    // 去掉「anima」:剩下 Illustrious + 「style」,一个都没有
    fireEvent.click(within(chips).getAllByRole("button", { name: "modelLibraryChipRemoveFamily" })[0]);
    expect(screen.queryByRole("list", { name: "modelLibraryTitle" })).toBeNull();
    expect(screen.getByText("modelLibraryNoMatchTitle")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "modelLibraryClearFilters" }));
    expect(cards()).toHaveLength(5);
    expect((screen.getByRole("textbox", { name: "modelLibrarySearch" }) as HTMLInputElement).value).toBe("");
    expect(screen.queryByRole("group", { name: "modelLibraryActiveFilters" })).toBeNull();

    fireEvent.change(screen.getByRole("textbox", { name: "modelLibrarySearch" }), { target: { value: "anima" } });
    fireEvent.click(screen.getByRole("button", { name: "libraryClearAll" }));
    expect(cards()).toHaveLength(5);
  });

  it("排序:名字按自然顺序,大小和改动时间大的 / 新的在前", async () => {
    await openLibrary();
    expect(names()).toEqual([
      "anima_style.safetensors", "AWPainting_IL.safetensors", "detail.safetensors", "pony_style.safetensors", "sd_xl_base.safetensors",
    ]);
    fireEvent.keyDown(screen.getByRole("combobox", { name: "modelLibrarySort" }), { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "modelLibrarySortSize" }));
    expect(names()).toEqual([
      "AWPainting_IL.safetensors", "sd_xl_base.safetensors", "detail.safetensors", "pony_style.safetensors", "anima_style.safetensors",
    ]);
    fireEvent.keyDown(screen.getByRole("combobox", { name: "modelLibrarySort" }), { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "modelLibrarySortModified" }));
    expect(names()[0]).toBe("pony_style.safetensors");
  });

  it("窄窗口:左边那一列收成工具条最前面的下拉", async () => {
    narrowWindow();
    await openLibrary();
    expect(screen.queryByRole("tablist")).toBeNull();
    const picker = screen.getByRole("combobox", { name: "modelLibraryFolders" });
    fireEvent.keyDown(picker, { key: "Enter" });
    expect(screen.getAllByRole("option").map((one) => one.textContent)).toEqual([
      "modelLibraryAll 5", "loras 3", "checkpoints 2", "modelMissingTitle 1",
    ]);
    fireEvent.click(screen.getByRole("option", { name: "loras 3" }));
    expect(cards()).toHaveLength(3);
  });

  it("点开是详情:底模和凭的是什么、触发词来自训练标签时说清楚、在用的工作流、文件头里的元数据", async () => {
    api.getModelDetail.mockResolvedValue({ folder: "loras", name: "detail.safetensors",
                                           metadata: { ss_output_name: "detail_tweaker" }, tags: [{ tag: "1girl", count: 45 }] });
    await openLibrary();
    const card = cards().find((item) => item.textContent?.includes("detail.safetensors"))!;
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
      exists: false, note: "" });
    api.startModelDownload.mockResolvedValue(job({ status: "queued", progress: 0, message: "排队" }));
    api.getJob.mockResolvedValue(job({}));
    api.cancelJob.mockResolvedValue(job({ status: "failed" }));
    await openLibrary();
    fireEvent.click(folderTab("modelMissingTitle 1"));
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
    // 发起之后左栏多出「下载记录」,并且切过去看进度
    const downloads = await screen.findByRole("region", { name: "modelDownloadsTitle" });
    expect(folderTab("modelLibraryDownloadsNav 1").getAttribute("aria-selected")).toBe("true");
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
      exists: true, note: "" });
    await openLibrary();
    fireEvent.click(screen.getByRole("button", { name: /modelLibraryDownload/ }));
    const link = await screen.findByPlaceholderText("modelDownloadLinkPlaceholder");
    fireEvent.change(link, { target: { value: "https://civitai.com/models/4?modelVersionId=5" } });
    fireEvent.click(screen.getByRole("button", { name: "modelDownloadResolve" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("modelDownloadExists");
    // Civitai 给的是「模型名 · 版本名」,不是文件名:标成「模型」,文件名在下面那一格
    expect(screen.getByText("D · v1").closest("div")?.textContent).toContain("modelDownloadModelName");
    const confirm = screen.getByRole("button", { name: /modelDownloadConfirm/ }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.click(within(alert).getByRole("button"));
    expect((screen.getByDisplayValue("detail (1).safetensors") as HTMLInputElement).value).toBe("detail (1).safetensors");
    expect(confirm.disabled).toBe(false);
  });

  it("经 ComfyUI-Manager 下 Civitai 又要带令牌:提醒令牌会留在那台机器的任务记录里,另说两个限制", async () => {
    api.getModelLibrary.mockResolvedValue(library({ download: { route: "manager", note: "经 ComfyUI-Manager(V4.2.1)下载" } }));
    api.resolveModelLink.mockResolvedValue({ source: "civitai", url: "https://civitai.com/api/download/models/5", page: "",
      filename: "chibi.safetensors", size: 1024, folder: "loras", family: "", triggers: [], title: "", exists: false,
      note: "", uses_token: true });
    await openLibrary();
    fireEvent.click(screen.getByRole("button", { name: /modelLibraryDownload/ }));
    fireEvent.change(await screen.findByPlaceholderText("modelDownloadLinkPlaceholder"),
                     { target: { value: "https://civitai.com/models/4?modelVersionId=5" } });
    fireEvent.click(screen.getByRole("button", { name: "modelDownloadResolve" }));
    const caution = await screen.findByRole("note", { name: "modelDownloadManagerCaution" });
    expect(caution.textContent).toContain("modelDownloadCivitaiTokenInUrl");
    expect(caution.textContent).toContain("modelDownloadManagerNoProgress");
    expect(caution.textContent).toContain("modelDownloadManagerCancel");
    expect((screen.getByRole("button", { name: /modelDownloadConfirm/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("不带令牌、或者本机那条路:不提令牌;本机那条路也没有 Manager 的那两个限制", async () => {
    api.getModelLibrary.mockResolvedValue(library({ download: { route: "manager", note: "" } }));
    api.resolveModelLink.mockResolvedValue({ source: "civitai", url: "https://civitai.com/api/download/models/5", page: "",
      filename: "chibi.safetensors", size: 1024, folder: "loras", family: "", triggers: [], title: "", exists: false,
      note: "", uses_token: false });
    await openLibrary();
    fireEvent.click(screen.getByRole("button", { name: /modelLibraryDownload/ }));
    fireEvent.change(await screen.findByPlaceholderText("modelDownloadLinkPlaceholder"),
                     { target: { value: "https://civitai.com/models/4?modelVersionId=5" } });
    fireEvent.click(screen.getByRole("button", { name: "modelDownloadResolve" }));
    const caution = await screen.findByRole("note", { name: "modelDownloadManagerCaution" });
    expect(caution.textContent).not.toContain("modelDownloadCivitaiTokenInUrl");
    expect(caution.textContent).toContain("modelDownloadManagerNoProgress");
  });

  it("这台服务器下不了:说为什么,点不了下载", async () => {
    api.getModelLibrary.mockResolvedValue(library({ download: { route: "none", note: "在那台机器上装 ComfyUI-Manager" } }));
    api.resolveModelLink.mockResolvedValue({ source: "direct", url: "https://example.com/x.safetensors", page: "",
      filename: "x.safetensors", size: null, folder: "", family: "", triggers: [], title: "", exists: false,
      note: "" });
    await openLibrary();
    fireEvent.click(folderTab("modelMissingTitle 1"));
    const missing = screen.getByRole("region", { name: "modelMissingTitle" });
    fireEvent.click(within(missing).getByRole("button", { name: /modelMissingDownload/ }));
    expect(await screen.findByText(/在那台机器上装 ComfyUI-Manager/)).toBeTruthy();
    expect(screen.getByText("modelDownloadCannot")).toBeTruthy();
    expect((screen.getByRole("button", { name: /modelDownloadConfirm/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("不撞名的建议:按目录里已有的名字往后数", () => {
    const taken = new Set(["a.safetensors", "a (1).safetensors"]);
    expect(freeName("a.safetensors", taken)).toBe("a (2).safetensors");
    expect(freeName("noext", new Set(["noext"]))).toBe("noext (1)");
  });
});

