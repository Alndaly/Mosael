/** @vitest-environment jsdom */

/**
 * 模型库(ADR 0034):一个连接那台服务器上的模型文件。不认识任何一家插件 —— 数据是 `/model-library` 给的,这里看的是
 * 怎么摆、怎么下:
 *
 * - 左边一列目录(按数量排、空的不列,缺的模型和下载记录是钉在底部的特殊项),上下方向键切换,窄窗口收成下拉;
 * - 顶上一条工具条:搜索(写着当前范围有几个)、按底模多选(只列当前目录里有的)、排序;生效的筛选一个个能去掉;
 * - 三档显示方式(大卡片 / 小卡片 / 列表),记在本机;
 * - 还在读、读不出来、空着:状态在工具条下面的整块里上下左右居中;读不出来给「重试」和「去检查连接设置」,
 *   工具条上的搜索、筛选、下载不装作「0 个文件」;
 * - 预览图分档(清晰 / 轻度模糊 / 重度模糊 / 不显示)、NSFW 单独管:记在本机,模糊的悬停或点开看清
 *   (细则、NSFW、右键菜单在 ModelLibrary.info.dom.test.tsx);
 * - 有预览图用宿主的预览地址,没有就是按目录分的占位;
 * - 点开是详情:顶上一条固定头(返回、名字、目录·大小·底模、常用操作),下面左边预览、右边概要 / 在用的工作流 /
 *   元数据,两栏各自滚(窄窗口上下排、一起滚);元数据能搜,长值折叠、能展开、能复制,大段 JSON 格式化显示;
 * - 「用它生成」:挑一张能选这个文件的工作流(在用它的排前面),带着那一格和作者写的触发词交给 AI 工作台;
 * - 工作流缺的模型一键下载:下载框带着地址、目录、文件名,解析之后确认,发起的任务在模型库里看得到进度、能取消;
 * - 同名文件不覆盖:换一个名字(给建议)之前「下载」点不了;这台服务器下不了时也点不了,并说为什么。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getModelLibrary: vi.fn(),
  getLocalNsfw: vi.fn(async () => ({ status: "missing", message: "", size_bytes: 22404720, pending: 0, scored: 0 })),
  installLocalNsfw: vi.fn(),
  getModelDetail: vi.fn(),
  resolveModelLink: vi.fn(),
  startModelDownload: vi.fn(),
  getJob: vi.fn(),
  cancelJob: vi.fn(),
  listGenerationOptions: vi.fn(),
  modelPreviewUrl: (instance: string, folder: string, name: string) => `preview://${instance}/${folder}/${name}`,
  modelThumbnailUrl: (instance: string, folder: string, name: string) => `thumbnail://${instance}/${folder}/${name}`,
}));
vi.mock("@/api/client", () => api);
vi.mock("@/api/domains/generation", () => ({ listGenerationOptions: api.listGenerationOptions }));
const handoff = vi.hoisted(() => vi.fn());
vi.mock("@/lib/generationHandoff", () => ({ handOffToGeneration: handoff }));
//: 大图走应用共用的灯箱(App 根上的 Provider);这里只看有没有交给它
const imagePreview = vi.hoisted(() => vi.fn());
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: imagePreview, isImagePreviewOpen: false }) }));
//: 文本编码器那几句要拼进底模名才看得出写了什么:这几条给真文案,别的照旧回键名
const ENCODER_TEXT = vi.hoisted((): Record<string, string> => ({
  modelEncoderRole: "文本编码器",
  modelEncoderUnknown: "认不出是哪一种",
  modelEncoderPairs: "常配 {families}",
  modelEncoderPairsMore: "常配 {families} 等 {n} 种",
  modelEncoderListSep: "、",
  modelLibraryFamilyCountPaired: "{n} · 常配 {m}",
  modelLibraryFamilyOnlyPaired: "常配 {m}",
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => ENCODER_TEXT[key] ?? key,
  usePreferences: () => ({ locale: "zh" }),
}));

import type { Job, ModelLibrary, PluginInstance } from "@/api/client";
import { hoverHint, readHint } from "@/test/hint";
import { ConnectionLibraries } from "./ConnectionLibraries";
import { ModelLibraryDialog, freeName } from "./ModelLibrary";

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
        preview_origin: "", preview_kind: "image", used_by: [{ id: "portrait.json", label: "portrait" }] },
      { folder: "checkpoints", name: "AWPainting_IL.safetensors", size: 6938041004, modified: 1700000001,
        family: "Illustrious", family_source: "filename", triggers: [], triggers_source: "", title: "", has_preview: false, preview_origin: "", preview_kind: "image",
        used_by: [] },
      { folder: "loras", name: "detail.safetensors", size: 228456516, modified: 1700000002, family: "Illustrious",
        family_source: "metadata", triggers: ["1girl", "solo"], triggers_source: "tags", title: "detail_tweaker",
        has_preview: true, preview_origin: "", preview_kind: "image", used_by: [{ id: "declaring.json", label: "declaring" }] },
      { folder: "loras", name: "sub\\anima_style.safetensors", size: 1000, modified: 1700000003, family: "anima",
        family_source: "metadata", triggers: ["anima style"], triggers_source: "metadata", title: "", has_preview: false, preview_origin: "", preview_kind: "image",
        used_by: [] },
      { folder: "loras", name: "pony_style.safetensors", size: 50000000, modified: 1700000010, family: "Pony",
        family_source: "filename", triggers: [], triggers_source: "", title: "", has_preview: false, preview_origin: "", preview_kind: "image", used_by: [] },
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
  wrap(<ConnectionLibraries instance={instance} workspaceId="w1" models />);
  fireEvent.click(screen.getByRole("button", { name: "modelLibraryOpen" }));
  return within(await screen.findByRole("list", { name: "modelLibraryTitle" }));
}

async function openLibraryAs(role: "list" | "table") {
  wrap(<ConnectionLibraries instance={instance} workspaceId="w1" models />);
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

/** 窗口只有 `width` 宽:`(max-width: Npx)` 里 N 不小于它的都算匹配。 */
function narrowWindow(width = 700) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string) => ({
      matches: Number(/max-width: (\d+)px/.exec(query)?.[1] ?? 0) >= width, media: query, onchange: null,
      addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

/** 详情左栏(并排时是左边那一栏,上下排时是整页一起滚的那一块)。 */
const detailMedia = () =>
  (document.querySelector("[data-library-detail-pane='media']") ?? document.querySelector("[data-library-detail-scroll='both']")) as HTMLElement;

/**
 * 详情左栏的占位是一个真的框:和卡片一样 3:4、占满这一栏的宽、高度有上限(并排 640、上下排半屏)、描着边(浅色主题下
 * 底色和弹窗表面几乎一样),图标和字在框里居中。
 */
function expectPreviewFrame(frame: HTMLElement | null) {
  expect(frame).toBeTruthy();
  for (const name of ["aspect-[3/4]", "w-full", "max-h-[640px]", "[[data-library-detail-scroll=both]_&]:max-h-[50dvh]",
    "border", "grid", "place-items-center", "content-center"]) {
    expect(frame!.classList.contains(name), name).toBe(true);
  }
  expect(frame!.querySelector(":scope > svg")).toBeTruthy();
  expect(frame!.textContent).toBe("modelNoPreview");
}

async function openDetail(name = "detail.safetensors", metadata: Record<string, string> = { ss_output_name: "detail_tweaker" }) {
  api.getModelDetail.mockResolvedValue({ folder: "loras", name, metadata, tags: [{ tag: "1girl", count: 45 }] });
  await openLibrary();
  const card = cards().find((item) => item.textContent?.includes(name))!;
  fireEvent.click(within(card).getByRole("button", { name }));
  return await screen.findByRole("button", { name: "modelLibraryBack" });
}

/** 这个连接上的一张工作流(生成选项):哪几格选哪个模型目录的文件、可选值是哪些。 */
function workflow(model: string, slots: Record<string, { folder: string; options: string[] }>) {
  return {
    id: `p9:image:${model}`, provider_profile_id: "p9", profile_name: "ComfyUI · 192.168.3.15", provider: "plugin:dev.mosael.comfyui",
    kind: "image", model, label: `ComfyUI · 192.168.3.15 · ${model.replace(/\.json$/, "")}`, plugin_instance_id: "i1",
    capabilities: {
      modes: ["text-to-image"],
      parameter_keys: Object.keys(slots),
      parameter_schema: Object.fromEntries(Object.entries(slots).map(([key, slot]) => [
        key, { type: "string", title: key, enum: slot.options, "x-model-folder": slot.folder },
      ])),
    },
    capabilities_known: true, adapter_available: true, is_default: false,
  };
}

const WORKFLOWS = [
  workflow("portrait.json", {
    "4.ckpt_name": { folder: "checkpoints", options: ["sd_xl_base.safetensors"] },
    "9.lora_name": { folder: "loras", options: ["detail.safetensors"] },
  }),
  workflow("declaring.json", { "36.lora_name": { folder: "loras", options: ["detail.safetensors", "sub\\anima_style.safetensors"] } }),
  workflow("upscale.json", {}),
  // 别的连接上的工作流不算
  { ...workflow("elsewhere.json", { "1.lora_name": { folder: "loras", options: ["detail.safetensors"] } }), plugin_instance_id: "i2" },
];

//: 合并模型带的那种大段 JSON(sd_merge_models)
const MERGE = JSON.stringify({
  sd_merge_models: {
    a1b2: { name: "animagine-xl-3.1", legacy_hash: "e3c47aed" },
    c3d4: { name: "pony", legacy_hash: "67ab2fd8" },
  },
});

const wideMatchMedia = window.matchMedia;

const clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };

beforeEach(() => {
  window.localStorage.clear();
  clipboard.writeText.mockClear();
  handoff.mockReset();
  api.listGenerationOptions.mockReset();
  api.listGenerationOptions.mockImplementation(async (kind: string) => (kind === "image" ? WORKFLOWS : []));
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: clipboard });
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
    expect(api.getModelLibrary).toHaveBeenCalledWith("i1", "safest");
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

  it("有预览图用宿主缩好的缩略图(详情页才要原图),没有就是按目录分的占位;大卡片上写着目录和子目录", async () => {
    await openLibrary();
    fireEvent.click(screen.getByRole("radio", { name: "libraryDensityLarge" }));
    fireEvent.click(folderTab("loras 3"));
    const detail = cards().find((item) => item.textContent?.includes("detail.safetensors"))!;
    expect(within(detail).getByRole("img").getAttribute("src")).toBe("thumbnail://i1/loras/detail.safetensors");
    const anima = cards().find((item) => item.textContent?.includes("anima_style.safetensors"))!;
    expect(anima.querySelector("[data-placeholder='loras']")).toBeTruthy();
    expect(anima.textContent).toContain("loras/sub");
  });

  it("三档显示方式:默认小卡片;选了哪一档记在本机,下次打开还是它", async () => {
    await openLibrary();
    const group = screen.getByRole("radiogroup", { name: "libraryDensity" });
    expect(within(group).getByRole("radio", { name: "libraryDensitySmall" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("list", { name: "modelLibraryTitle" }).getAttribute("data-density")).toBe("small");
    fireEvent.click(within(group).getByRole("radio", { name: "libraryDensityList" }));
    expect(screen.queryByRole("list", { name: "modelLibraryTitle" })).toBeNull();
    cleanup();

    await openLibraryAs("table");
    expect(screen.getByRole("radio", { name: "libraryDensityList" }).getAttribute("aria-checked")).toBe("true");
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

  it("工具条一行放不下时按优先级收成图标:先收「底模」的字,最后收「下载模型」;名字照样在按钮上(读屏、悬停说明)", async () => {
    await openLibrary();
    const bar = document.querySelector<HTMLElement>("[data-library-toolbar]")!;
    //: 收不收看工具条自己有多宽(容器查询),不看窗口 —— 左边那一列占掉多少,窗口宽度看不出来。
    expect(bar.className).toContain("@container/library-toolbar");
    const family = within(bar).getByRole("button", { name: /modelLibraryFamilyLabel/ });
    const download = within(bar).getByRole("button", { name: "modelLibraryDownload" });
    expect(family.querySelector("[data-toolbar-label]")?.getAttribute("data-toolbar-label")).toBe("first");
    expect(download.querySelector("[data-toolbar-label]")?.getAttribute("data-toolbar-label")).toBe("last");
    //: 收起之后剩下的是图标:「⬇ 下载模型」本来就带着;「底模 ▾」收起时换上筛选图标。名字在 aria-label 上,悬停说明里也是它。
    expect(family.querySelector("[data-toolbar-icon]")?.getAttribute("data-toolbar-icon")).toBe("first");
    expect(download.querySelector(":scope > svg")).toBeTruthy();
    expect(await readHint(download)).toBe("modelLibraryDownload");
    //: 勾了底模,按钮上写的是几种,不是名字(名字在下面那行筛选里):勾一个长名字不会把工具条挤成两行。
    pickFamilies("Illustrious 2");
    expect(within(bar).getByRole("button", { name: /modelLibraryFamilyLabel/ }).textContent).toBe("modelLibraryFamilyButton · 1");
    expect(screen.getByRole("group", { name: "modelLibraryActiveFilters" }).textContent).toContain("Illustrious");
  });

  it("还在读时点不了的「下载模型」也一样能收成图标,并说为什么点不了", async () => {
    api.getModelLibrary.mockReturnValue(new Promise(() => {}));
    wrap(<ConnectionLibraries instance={instance} workspaceId="w1" models />);
    fireEvent.click(screen.getByRole("button", { name: "modelLibraryOpen" }));
    const download = await screen.findByRole("button", { name: "modelLibraryDownload" });
    expect((download as HTMLButtonElement).disabled).toBe(true);
    expect(download.querySelector("[data-toolbar-label]")?.getAttribute("data-toolbar-label")).toBe("last");
    expect(await readHint(download)).toBe("modelLibraryDownloadmodelLibraryStillReading");
  });

  it("预览图模糊:默认清晰;选了重度模糊,卡片和列表里的预览图都先糊着(悬停 / 聚焦时看清),占位不模糊;记在本机", async () => {
    await openLibrary();
    const detail = () => cards().find((item) => item.textContent?.includes("detail.safetensors"))!;
    expect(within(detail()).getByRole("img").getAttribute("data-treatment")).toBe("clear");
    fireEvent.click(screen.getByRole("button", { name: "modelPreviewSettings" }));
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "modelPreviewLevel" })).getByRole("radio", { name: "modelPreviewLevelHeavy" }));
    const img = within(detail()).getByRole("img");
    expect(img.getAttribute("data-treatment")).toBe("heavy");
    expect(img.className).toContain("blur-xl");
    // 悬停 / 键盘聚焦到这张卡时看清:靠卡片上的 group/thumb
    expect(detail().querySelector("[data-library-item]")!.className).toContain("group/thumb");
    expect(img.className).toContain("group-hover/thumb:blur-none");
    expect(document.querySelectorAll("[data-placeholder][data-treatment]")).toHaveLength(0);
    cleanup();

    window.localStorage.setItem("mosael:tab:model-library.density", "list");
    const table = await openLibraryAs("table");
    const row = table.getAllByRole("row").find((one) => one.textContent?.includes("detail.safetensors"))!;
    expect(row.querySelector("img")!.getAttribute("data-treatment")).toBe("heavy");
  });

  it("还在读:加载中在工具条下面的整块里居中(没有左栏);搜索、筛选、下载不装作「0 个文件」", async () => {
    api.getModelLibrary.mockReturnValue(new Promise(() => {}));
    wrap(<ConnectionLibraries instance={instance} workspaceId="w1" models />);
    fireEvent.click(screen.getByRole("button", { name: "modelLibraryOpen" }));
    const status = await screen.findByRole("status");
    expect(status.textContent).toContain("modelLibraryLoading");
    expect(screen.queryByRole("tablist")).toBeNull();
    // 内容区是纵向弹性盒,状态撑满剩下的高度、自己居中:弹窗多高都在正中
    const content = status.closest("[data-library-content]") as HTMLElement;
    expect(content.className).toContain("flex-col");
    expect(status.className).toContain("flex-1");
    const search = screen.getByRole("textbox", { name: "modelLibrarySearchPending" }) as HTMLInputElement;
    expect(search.disabled).toBe(true);
    expect(search.placeholder).not.toMatch(/\d/);
    expect(screen.queryByRole("button", { name: /modelLibraryFamilyLabel/ })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "modelLibrarySort" })).toBeNull();
    expect(screen.queryByRole("radiogroup", { name: "libraryDensity" })).toBeNull();
    expect((screen.getByRole("button", { name: /modelLibraryDownload/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("读不出来:居中说清楚,给「重试」和「去检查连接设置」;工具条照样不装作 0 个文件", async () => {
    const onCheckSettings = vi.fn();
    api.getModelLibrary.mockRejectedValueOnce(new Error("连不上这台 ComfyUI,确认它在运行、地址填对"));
    wrap(<ConnectionLibraries instance={instance} workspaceId="w1" models onCheckSettings={onCheckSettings} />);
    fireEvent.click(screen.getByRole("button", { name: "modelLibraryOpen" }));
    const title = await screen.findByText("modelLibraryErrorTitle");
    const state = title.closest(".empty-state") as HTMLElement;
    expect(state.className).toContain("m-auto");
    expect(state.closest("[data-library-content]")).toBeTruthy();
    expect(state.textContent).toContain("连不上这台 ComfyUI,确认它在运行、地址填对");
    expect((screen.getByRole("textbox", { name: "modelLibrarySearchPending" }) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: /modelLibraryDownload/ }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(within(state).getByRole("button", { name: "modelLibraryCheckSettings" }));
    expect(onCheckSettings).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByText("modelLibraryErrorTitle")).toBeNull());
  });

  it("报错的原文(errno、地址)收进「详情」,正文只说第一行那句人话", async () => {
    api.getModelLibrary.mockRejectedValueOnce(new Error("连不上这台 ComfyUI,确认它在运行、地址填对\nhttp://127.0.0.1:8188:[Errno 61] Connection refused"));
    wrap(<ConnectionLibraries instance={instance} workspaceId="w1" models />);
    fireEvent.click(screen.getByRole("button", { name: "modelLibraryOpen" }));
    const state = (await screen.findByText("modelLibraryErrorTitle")).closest(".empty-state") as HTMLElement;
    expect(state.textContent).toContain("连不上这台 ComfyUI,确认它在运行、地址填对");
    expect(state.textContent).not.toContain("Errno");
    fireEvent.click(within(state).getByRole("button", { name: "errorDetails" }));
    expect(await within(state).findByText(/\[Errno 61\] Connection refused/)).toBeTruthy();
  });

  it("读不出来时点「重试」再问一遍,读到了就照常列出来", async () => {
    api.getModelLibrary.mockRejectedValueOnce(new Error("连不上这台 ComfyUI,确认它在运行、地址填对"));
    wrap(<ConnectionLibraries instance={instance} workspaceId="w1" models />);
    fireEvent.click(screen.getByRole("button", { name: "modelLibraryOpen" }));
    await screen.findByText("modelLibraryErrorTitle");
    // 没人接「去检查连接设置」(不在插件页上打开的)就不摆这颗按钮
    expect(screen.queryByRole("button", { name: "modelLibraryCheckSettings" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "retry" }));
    expect(await screen.findByRole("list", { name: "modelLibraryTitle" })).toBeTruthy();
    expect(api.getModelLibrary).toHaveBeenCalledTimes(2);
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

  it("详情页:顶上一条固定头 —— 返回、名字、目录 · 大小 · 底模、复制文件名;下面左右两栏各自滚动", async () => {
    const back = await openDetail();
    await waitFor(() => expect(document.activeElement).toBe(back));
    const head = back.closest("[data-library-detail-head]") as HTMLElement;
    expect(within(head).getByRole("heading", { name: "detail.safetensors" })).toBeTruthy();
    expect(head.textContent).toContain("loras");
    expect(head.textContent).toContain("228 MB");
    expect(head.textContent).toContain("Illustrious");
    fireEvent.click(within(head).getByRole("button", { name: /modelCopyName/ }));
    expect(clipboard.writeText).toHaveBeenCalledWith("detail.safetensors");
    const media = document.querySelector("[data-library-detail-pane='media']") as HTMLElement;
    const info = document.querySelector("[data-library-detail-pane='info']") as HTMLElement;
    expect(media.className).toContain("overflow-y-auto");
    expect(info.className).toContain("overflow-y-auto");
    // 头不在任何一栏里:滚到元数据时名字和操作还在
    expect(media.contains(head) || info.contains(head)).toBe(false);
    expect(within(media).getByRole("img").getAttribute("src")).toBe("preview://i1/loras/detail.safetensors");
  });

  it("窄窗口:详情改成上下排、整体一起滚", async () => {
    narrowWindow(800);
    await openDetail();
    expect(document.querySelector("[data-library-detail-pane]")).toBeNull();
    const both = document.querySelector("[data-library-detail-scroll='both']") as HTMLElement;
    expect(both.className).toContain("overflow-y-auto");
    expect(both.querySelector("img")).toBeTruthy();
    expect(both.textContent).toContain("modelOverview");
  });

  it("详情预览:有图时照旧按图自己的比例收进框里(并排 640、上下排半屏);预览图模糊时先糊着,能点「看清」", async () => {
    window.localStorage.setItem("mosael:model-previews", JSON.stringify({ level: "heavy", nsfw: "blur" }));
    await openDetail();
    const img = within(detailMedia()).getByRole("img");
    for (const name of ["object-contain", "w-full", "max-h-[640px]", "[[data-library-detail-scroll=both]_&]:max-h-[50dvh]"]) {
      expect(img.classList.contains(name), name).toBe(true);
    }
    expect(img.classList.contains("aspect-[3/4]")).toBe(false);
    expect(img.getAttribute("data-treatment")).toBe("heavy");
    fireEvent.click(within(detailMedia()).getByRole("button", { name: "modelRevealPreview" }));
    expect(within(detailMedia()).getByRole("img").getAttribute("data-treatment")).toBe("clear");
    expect(within(detailMedia()).queryByRole("button", { name: "modelRevealPreview" })).toBeNull();
  });

  it("详情预览:没有预览图是一个 3:4 的框,图标和「没有预览图」在框里居中;没有「看清」", async () => {
    window.localStorage.setItem("mosael:model-previews", JSON.stringify({ level: "heavy", nsfw: "blur" }));
    await openDetail("pony_style.safetensors");
    const media = detailMedia();
    expect(within(media).queryByRole("img")).toBeNull();
    expectPreviewFrame(media.querySelector<HTMLElement>("[data-detail-placeholder='loras']"));
    expect(within(media).queryByRole("button", { name: "modelRevealPreview" })).toBeNull();
  });

  it("详情预览:说有预览图、这张却取不到 —— 换成同一个 3:4 的框,不缩成顶上一条;「看清」跟着收起", async () => {
    window.localStorage.setItem("mosael:model-previews", JSON.stringify({ level: "heavy", nsfw: "blur" }));
    await openDetail();
    const media = detailMedia();
    fireEvent.error(within(media).getByRole("img"));
    expect(within(media).queryByRole("img")).toBeNull();
    expectPreviewFrame(media.querySelector<HTMLElement>("[data-detail-placeholder='loras']"));
    //: ModelThumb 自己那个占位沿用给图片的 max-h、没有高度 —— 详情里不该是它
    expect(media.querySelector("[data-placeholder]")).toBeNull();
    expect(within(media).queryByRole("button", { name: "modelRevealPreview" })).toBeNull();
  });

  it("详情预览:窄窗口上下排时,取不到图换上的框也在整页一起滚的那一块里", async () => {
    narrowWindow(800);
    await openDetail();
    const both = document.querySelector("[data-library-detail-scroll='both']") as HTMLElement;
    fireEvent.error(within(both).getByRole("img"));
    expectPreviewFrame(both.querySelector<HTMLElement>("[data-detail-placeholder='loras']"));
  });

  it("详情从这一个直接换到那一个(从工作流库跳过来):上一个取不到预览图,不影响下一个", async () => {
    api.getModelLibrary.mockResolvedValue(library({
      models: library().models?.map((one) => (one.name === "pony_style.safetensors" ? { ...one, has_preview: true } : one)),
    }));
    api.getModelDetail.mockImplementation(async (_id: string, folder: string, name: string) => ({ folder, name, metadata: {}, tags: [] }));
    const dialog = (name: string, at: number) => (
      <ModelLibraryDialog open onOpenChange={() => undefined} instance={instance} workspaceId="w1"
                          focus={{ model: { folder: "loras", name }, at }} />
    );
    const view = wrap(dialog("detail.safetensors", 1));
    await screen.findByRole("heading", { name: "detail.safetensors" });
    fireEvent.error(within(detailMedia()).getByRole("img"));
    expect(detailMedia().querySelector("[data-detail-placeholder]")).toBeTruthy();

    view.rerender(dialog("pony_style.safetensors", 2));
    await screen.findByRole("heading", { name: "pony_style.safetensors" });
    expect(within(detailMedia()).getByRole("img").getAttribute("src")).toBe("preview://i1/loras/pony_style.safetensors");
  });

  it("概要:底模和判据(弱一档的一行说明)、触发词点一下复制;「在哪些工作流里用到」跳到那一节", async () => {
    await openDetail();
    const overview = screen.getByRole("region", { name: "modelOverview" });
    expect(overview.textContent).toContain("modelFamilySourceMetadata");
    expect(overview.textContent).toContain("modelTriggersFromTags");
    fireEvent.click(within(overview).getByRole("button", { name: "1girl" }));
    expect(clipboard.writeText).toHaveBeenCalledWith("1girl");

    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView");
    fireEvent.click(screen.getByRole("button", { name: /modelUsedCount/ }));
    const used = screen.getByRole("region", { name: "modelUsedBy" });
    expect(scrolled).toHaveBeenCalled();
    await waitFor(() => expect(used.contains(document.activeElement)).toBe(true));
    expect(used.textContent).toContain("declaring");
  });

  it("底模的三种判据各说各的:权重结构认出的实色、说凭的是权重;放大模型这类写「不适用」,筛选里单列在最后", async () => {
    const base = library();
    api.getModelLibrary.mockResolvedValue(library({
      folders: [...(base.folders ?? []), { name: "upscale_models", count: 1 }],
      models: [
        ...(base.models ?? []),
        { folder: "checkpoints", name: "dessert.safetensors", size: 6938041004, modified: 1700000020, family: "SDXL",
          family_source: "weights", triggers: [], triggers_source: "", title: "", has_preview: false, preview_origin: "", preview_kind: "image", used_by: [] },
        { folder: "upscale_models", name: "4x-UltraSharp.pth", size: 67000000, modified: 1700000021, family: "",
          family_source: "not_applicable", triggers: [], triggers_source: "", title: "", has_preview: false, preview_origin: "", preview_kind: "image", used_by: [] },
      ],
    }));
    await openLibrary();
    fireEvent.click(screen.getByRole("button", { name: /modelLibraryFamilyLabel/ }));
    const menu = screen.getByRole("menu", { name: "modelLibraryFamilyLabel" });
    const labels = within(menu).getAllByRole("menuitemcheckbox").map((item) => item.getAttribute("aria-label"));
    expect(labels.at(-1)).toBe("modelLibraryFamilyNotApplicable 1");
    expect(labels.some((label) => label?.includes("__"))).toBe(false);
    fireEvent.keyDown(menu, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());

    api.getModelDetail.mockResolvedValue({ folder: "checkpoints", name: "dessert.safetensors", metadata: {}, tags: [] });
    fireEvent.click(within(cards().find((item) => item.textContent?.includes("dessert.safetensors"))!)
      .getByRole("button", { name: "dessert.safetensors" }));
    await screen.findByRole("button", { name: "modelLibraryBack" });
    expect(screen.getByRole("region", { name: "modelOverview" }).textContent).toContain("modelFamilySourceWeights");
    fireEvent.click(screen.getByRole("button", { name: "modelLibraryBack" }));

    api.getModelDetail.mockResolvedValue({ folder: "upscale_models", name: "4x-UltraSharp.pth", metadata: {}, tags: [] });
    fireEvent.click(await screen.findByRole("tab", { name: "upscale_models 1" }));
    fireEvent.click(within(cards()[0]).getByRole("button", { name: "4x-UltraSharp.pth" }));
    await screen.findByRole("button", { name: "modelLibraryBack" });
    const overview = screen.getByRole("region", { name: "modelOverview" }).textContent;
    expect(overview).toContain("modelLibraryFamilyNotApplicable");
    expect(overview).toContain("modelFamilyNotApplicableHint");
    expect(overview).not.toContain("modelLibraryFamilyUnknown");
  });

  it("文本编码器:不写「不适用」,写是哪一种和常配的底模;按底模筛时常配它的一起列出、标「常配」,不算那个底模的", async () => {
    const base = library();
    const encoder = (name: string, kind: string, label: string, pairs: string[], source = "weights") => ({
      folder: "text_encoders", name, size: 9000000000, modified: 1700000030, family: "", family_source: "not_applicable",
      triggers: [], triggers_source: "", title: "", has_preview: false, preview_origin: "", preview_kind: "image", used_by: [],
      encoder: { kind, label, source, pairs },
    });
    api.getModelLibrary.mockResolvedValue(library({
      folders: [...(base.folders ?? []), { name: "text_encoders", count: 3 }],
      models: [
        ...(base.models ?? []),
        encoder("t5xxl_fp16.safetensors", "t5_xxl", "T5-XXL", ["Flux", "SD 3", "HiDream", "LTX-Video", "Flux Kontext", "Chroma"]),
        encoder("qwen3vl_4b.safetensors", "qwen3vl_4b", "Qwen3-VL 4B", ["Krea 2", "Flux.2"], "filename"),
        encoder("mystery.safetensors", "", "", [], ""),
      ],
    }));
    await openLibrary();
    fireEvent.click(folderTab("text_encoders 3"));
    const card = (name: string) => cards().find((item) => item.textContent?.includes(name))!;
    const pairs = (name: string) => card(name).querySelector("[data-encoder-pairs]")?.textContent;
    expect(card("t5xxl_fp16").textContent).toContain("T5-XXL");
    expect(pairs("t5xxl_fp16")).toBe("常配 Flux、SD 3、HiDream 等 6 种");
    expect(pairs("qwen3vl_4b")).toBe("常配 Krea 2、Flux.2");
    expect(card("mystery").textContent).toContain("文本编码器 · 认不出是哪一种");
    expect(card("t5xxl_fp16").textContent).not.toContain("modelLibraryFamilyNotApplicable");
    expect(await hoverHint(within(card("qwen3vl_4b")).getByText("Qwen3-VL 4B"))).toBe("modelEncoderSourceFilename");

    // 在文本编码器目录里也能按底模挑:常配的底模列进筛选,数目写明几个是常配的
    fireEvent.click(screen.getByRole("button", { name: /modelLibraryFamilyLabel/ }));
    let menu = screen.getByRole("menu", { name: "modelLibraryFamilyLabel" });
    const labels = within(menu).getAllByRole("menuitemcheckbox").map((item) => item.getAttribute("aria-label"));
    expect(labels).toContain("Krea 2 常配 1");
    expect(labels.at(-1)).toBe("modelLibraryFamilyNotApplicable 3");
    fireEvent.keyDown(menu, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());

    // 全部里按 SDXL 筛:SDXL 的照旧;没有常配 SDXL 的编码器,一个都不多
    fireEvent.click(folderTab("modelLibraryAll 8"));
    menu = pickFamilies("SDXL 1");
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(names()).toEqual(["sd_xl_base.safetensors"]);
    // 换成 Flux:没有 Flux 的模型,常配 Flux 的 T5-XXL 列出来,勾着的那一种排在「常配」最前、写重一点
    menu = pickFamilies("SDXL 1", "Flux 常配 1");
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(names()).toEqual(["t5xxl_fp16.safetensors"]);
    const flux = within(card("t5xxl_fp16").querySelector("[data-encoder-pairs]") as HTMLElement).getByText("Flux");
    expect(flux.className).toContain("text-foreground");
    menu = pickFamilies("Flux 常配 1", "HiDream 常配 1");
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(pairs("t5xxl_fp16")).toBe("常配 HiDream、Flux、SD 3 等 6 种");

    // 详情:「文本编码器 · T5-XXL」,下面一排常配的底模
    api.getModelDetail.mockResolvedValue({ folder: "text_encoders", name: "t5xxl_fp16.safetensors", metadata: {}, tags: [] });
    fireEvent.click(within(card("t5xxl_fp16")).getByRole("button", { name: "t5xxl_fp16.safetensors" }));
    await screen.findByRole("button", { name: "modelLibraryBack" });
    const overview = screen.getByRole("region", { name: "modelOverview" });
    expect(overview.textContent).toContain("文本编码器 · T5-XXL");
    expect(within(overview).getByLabelText("常配 HiDream、Flux、SD 3、LTX-Video、Flux Kontext、Chroma")).toBeTruthy();
    expect(overview.textContent).toContain("modelEncoderSourceWeights");
    expect(overview.textContent).toContain("modelEncoderPairsNote");
    expect(overview.textContent).not.toContain("modelLibraryFamilyNotApplicable");
  });

  it("元数据:能搜;长值默认折叠、能展开、能复制;大段 JSON 格式化显示,不撑宽", async () => {
    await openDetail("detail.safetensors", { ss_output_name: "detail_tweaker", ss_network_dim: "32", sd_merge_models: MERGE });
    const meta = await screen.findByRole("region", { name: "modelMetadata" });
    await within(meta).findByText("sd_merge_models");
    const row = within(meta).getByText("sd_merge_models").closest("[data-meta-row]") as HTMLElement;
    expect(row.querySelector("pre")).toBeNull();
    const expand = within(row).getByRole("button", { name: "modelMetaExpand" });
    expect(expand.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(expand);
    const pre = row.querySelector("pre") as HTMLElement;
    expect(pre.textContent).toContain('\n  "sd_merge_models": {');
    expect(pre.className).toContain("overflow-auto");
    fireEvent.click(within(row).getByRole("button", { name: "modelMetaCopy" }));
    expect(clipboard.writeText).toHaveBeenCalledWith(MERGE);

    const search = within(meta).getByRole("searchbox", { name: "modelMetaSearch" });
    fireEvent.change(search, { target: { value: "dim" } });
    expect(within(meta).queryByText("sd_merge_models")).toBeNull();
    expect(within(meta).getByText("ss_network_dim")).toBeTruthy();
    fireEvent.change(search, { target: { value: "没有这个" } });
    expect(within(meta).getByText("modelMetaNoMatch")).toBeTruthy();
  });

  it("「用它生成」:只有一张工作流能选这个文件,点了直接交给 AI 工作台 —— 带着那一格和作者写的触发词", async () => {
    await openDetail("anima_style.safetensors");
    // 生成选项到了之前它点不了(按钮会换一颗):每次重新找
    const go = () => screen.getByRole("button", { name: /modelUseToGenerate/ }) as HTMLButtonElement;
    await waitFor(() => expect(go().disabled).toBe(false));
    fireEvent.click(go());
    expect(handoff).toHaveBeenCalledWith({
      providerProfileId: "p9", kind: "image", model: "declaring.json",
      declared: { "36.lora_name": "sub\\anima_style.safetensors" }, promptWords: ["anima style"],
    });
  });

  it("能选它的工作流不止一张:让人挑,在用它的排前面;从训练标签里猜的「触发词」不往提示词里塞", async () => {
    await openDetail("detail.safetensors");
    // 生成选项到了之前它点不了(按钮会换一颗):每次重新找
    const go = () => screen.getByRole("button", { name: /modelUseToGenerate/ }) as HTMLButtonElement;
    await waitFor(() => expect(go().disabled).toBe(false));
    fireEvent.click(go());
    const menu = screen.getByRole("menu", { name: "modelUseToGenerateMenu" });
    expect(within(menu).getAllByRole("menuitem").map((item) => item.textContent?.startsWith("declaring") ? "declaring" : item.textContent)).toEqual([
      "declaring", "portrait",
    ]);
    fireEvent.click(within(menu).getByRole("menuitem", { name: "portrait" }));
    expect(handoff).toHaveBeenCalledWith({
      providerProfileId: "p9", kind: "image", model: "portrait.json", declared: { "9.lora_name": "detail.safetensors" }, promptWords: [],
    });
  });

  it("没有哪张工作流能选它:点不了并说为什么;「在用的工作流」里的那几张点了也是交给 AI 工作台", async () => {
    await openDetail("AWPainting_IL.safetensors");
    await waitFor(() => expect(api.listGenerationOptions).toHaveBeenCalled());
    expect((screen.getByRole("button", { name: /modelUseToGenerate/ }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "modelLibraryBack" }));

    const sdxl = (await screen.findAllByRole("listitem")).find((item) => item.textContent?.includes("sd_xl_base.safetensors"))!;
    fireEvent.click(within(sdxl).getByRole("button", { name: "sd_xl_base.safetensors" }));
    const used = await screen.findByRole("region", { name: "modelUsedBy" });
    fireEvent.click(await within(used).findByRole("button", { name: "portrait" }));
    expect(handoff).toHaveBeenCalledWith({
      providerProfileId: "p9", kind: "image", model: "portrait.json", declared: { "4.ckpt_name": "sd_xl_base.safetensors" }, promptWords: [],
    });
  });

  it("点开是详情:底模和凭的是什么、触发词来自训练标签时说清楚、在用的工作流、文件头里的元数据", async () => {
    api.getModelDetail.mockResolvedValue({ folder: "loras", name: "detail.safetensors",
                                           metadata: { ss_output_name: "detail_tweaker" }, tags: [{ tag: "1girl", count: 45 }] });
    await openLibrary();
    const card = cards().find((item) => item.textContent?.includes("detail.safetensors"))!;
    fireEvent.click(within(card).getByRole("button", { name: "detail.safetensors" }));
    // 标题(概要里)和元数据里的 ss_output_name 都是它
    expect(await screen.findByText("ss_output_name")).toBeTruthy();
    expect(screen.getAllByText("detail_tweaker")).toHaveLength(2);
    expect(api.getModelDetail).toHaveBeenCalledWith("i1", "loras", "detail.safetensors");
    expect(screen.getAllByText("modelTriggersFromTags").length).toBeGreaterThan(0);
    expect(screen.getAllByText("modelFamilySourceMetadata").length).toBeGreaterThan(0);
    expect(screen.getByText("declaring")).toBeTruthy();
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

  it("在用的工作流:旁边一颗「在工作流库里看」,点了跳到工作流库那一张(行本身照旧是用它生成)", async () => {
    const showWorkflow = vi.fn();
    wrap(<ModelLibraryDialog open onOpenChange={() => undefined} instance={instance} workspaceId="w1" onShowWorkflow={showWorkflow} />);
    const sdxl = (await screen.findAllByRole("listitem")).find((item) => item.textContent?.includes("sd_xl_base.safetensors"))!;
    fireEvent.click(within(sdxl).getByRole("button", { name: "sd_xl_base.safetensors" }));
    const used = await screen.findByRole("region", { name: "modelUsedBy" });
    fireEvent.click(within(used).getByRole("button", { name: "modelShowInWorkflowLibrary" }));
    expect(showWorkflow).toHaveBeenCalledWith("portrait.json");
    expect(handoff).not.toHaveBeenCalled();
  });

  it("从工作流库跳过来:停到那一项", async () => {
    api.getModelDetail.mockResolvedValue({ folder: "loras", name: "detail.safetensors", metadata: {}, tags: [] });
    wrap(<ModelLibraryDialog open onOpenChange={() => undefined} instance={instance} workspaceId="w1"
                             focus={{ model: { folder: "loras", name: "detail.safetensors" }, at: 1 }} />);
    await screen.findByRole("button", { name: "modelLibraryBack" });
    expect(screen.getByRole("heading", { name: "detail.safetensors" })).toBeTruthy();
  });

  it("从工作流库跳过来下载缺的模型:下载框带着工作流里写的地址、目录和文件名", async () => {
    api.resolveModelLink.mockResolvedValue({ source: "huggingface", url: "https://huggingface.co/x/y/resolve/main/ae.safetensors",
      page: "", filename: "ae.safetensors", size: 335304388, folder: "vae", family: "", triggers: [], title: "",
      exists: false, note: "" });
    wrap(<ModelLibraryDialog open onOpenChange={() => undefined} instance={instance} workspaceId="w1"
                             focus={{ download: { url: "https://huggingface.co/x/y/resolve/main/ae.safetensors", folder: "vae",
                                                  name: "ae.safetensors" }, at: 1 }} />);
    await waitFor(() => expect(api.resolveModelLink).toHaveBeenCalledWith("i1", "https://huggingface.co/x/y/resolve/main/ae.safetensors"));
    expect(await screen.findByRole("button", { name: /modelDownloadConfirm/ })).toBeTruthy();
  });

  it("从工作流库跳过来下载一个没写地址的缺模型:下载框说清楚要找的是哪个文件", async () => {
    wrap(<ModelLibraryDialog open onOpenChange={() => undefined} instance={instance} workspaceId="w1"
                             focus={{ download: { folder: "checkpoints", name: "JANKUV5.safetensors" }, at: 1 }} />);
    const dialog = await screen.findByRole("dialog", { name: "modelDownloadTitle" });
    expect(dialog.textContent).toContain("modelDownloadWanted");
    expect(api.resolveModelLink).not.toHaveBeenCalled();
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

  it("ModelScope 的链接:来源写 ModelScope;经 ComfyUI-Manager 又填了令牌时,说令牌带不过去", async () => {
    api.getModelLibrary.mockResolvedValue(library({ download: { route: "manager", note: "" } }));
    api.resolveModelLink.mockResolvedValue({ source: "modelscope",
      url: "https://modelscope.cn/models/a/b/resolve/master/chibi.safetensors", page: "", filename: "chibi.safetensors",
      size: 1024, folder: "loras", family: "Illustrious", triggers: [], title: "Q 版画风", exists: false, note: "",
      uses_token: true });
    await openLibrary();
    fireEvent.click(screen.getByRole("button", { name: /modelLibraryDownload/ }));
    fireEvent.change(await screen.findByPlaceholderText("modelDownloadLinkPlaceholder"),
                     { target: { value: "https://modelscope.cn/models/a/b" } });
    fireEvent.click(screen.getByRole("button", { name: "modelDownloadResolve" }));
    const caution = await screen.findByRole("note", { name: "modelDownloadManagerCaution" });
    expect(caution.textContent).toContain("modelDownloadModelscopeTokenUnsupported");
    expect(caution.textContent).not.toContain("modelDownloadCivitaiTokenInUrl");
    expect(screen.getByText("modelDownloadSourceModelscope")).toBeTruthy();
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

