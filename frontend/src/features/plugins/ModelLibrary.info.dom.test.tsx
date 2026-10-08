/** @vitest-environment jsdom */

/**
 * 模型库的「模型信息」(ADR 0038 §9):预览图分档、NSFW 单独管、手动标记,以及一个模型的右键菜单。
 *
 * - 两组设置记在本机(`mosael:model-previews`):预览图「清晰 / 轻度 / 重度 / 不显示」,NSFW「照常 / 模糊 / 不显示」,
 *   独立生效、取更严的那一档;不显示的不去取图(只画图标);
 * - 判成 NSFW 的卡片上一枚角标,悬停说凭什么(手动、Civitai、本机识别、训练标签和名字);
 * - 详情里能标成是 / 不是、改回自动判断,改了马上生效(宿主回新的判断,不重新列);
 * - 右键、卡片上的 ⋯、Shift+F10 打开同一个菜单,条目按模型的状态出,点不了的写为什么;
 * - 「工作流缺的模型」那一页右键能下载、复制名字和地址;
 * - 那台服务器上没有预览图、用了 Civitai 的示例图的,卡片角上标「来自 Civitai」;「存为预览图」先确认(按文件名对上的
 *   多说一句),写不回时点不了并说缺什么;「为缺预览图的模型补图」先确认、是一个后台任务,做完重新列;
 * - 详情里写原链接和怎么知道的;没有就说没有,「在 Civitai 上找」(后台任务)。
 */

import React from "react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getModelLibrary: vi.fn(),
  getLocalNsfw: vi.fn(),
  installLocalNsfw: vi.fn(),
  getModelDetail: vi.fn(),
  resolveModelLink: vi.fn(),
  startModelDownload: vi.fn(),
  markModelNsfw: vi.fn(),
  saveModelPreview: vi.fn(),
  startModelLookup: vi.fn(),
  getModelLookup: vi.fn(),
  getJob: vi.fn(),
  cancelJob: vi.fn(),
  listGenerationOptions: vi.fn(),
  modelPreviewUrl: (instance: string, folder: string, name: string) => `preview://${instance}/${folder}/${name}`,
  modelThumbnailUrl: (instance: string, folder: string, name: string) => `thumbnail://${instance}/${folder}/${name}`,
}));
vi.mock("@/api/client", () => api);
const authMe = vi.hoisted(() => vi.fn());
vi.mock("@/app/auth", () => ({ useIsDeploymentAdmin: () => useQuery({ queryKey: ["auth-me"], queryFn: authMe }).data?.is_deployment_admin ?? false }));
vi.mock("@/api/domains/generation", () => ({ listGenerationOptions: api.listGenerationOptions }));
const handoff = vi.hoisted(() => vi.fn());
vi.mock("@/lib/generationHandoff", () => ({ handOffToGeneration: handoff }));
const imagePreview = vi.hoisted(() => vi.fn());
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: imagePreview, isImagePreviewOpen: false }) }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh" }),
}));

import type { ModelFile, ModelLibrary, ModelLocalNsfw, ModelNsfw, PluginInstance } from "@/api/client";
import { hoverHint, readHint } from "@/test/hint";
import { ModelLibraryDialog } from "./ModelLibrary";

const instance = { id: "i1", name: "ComfyUI · 192.168.3.15", blocked_reason: "" } as PluginInstance;
const SAFE: ModelNsfw = { flagged: false, manual: null, reasons: [] };
const BY_TAGS: ModelNsfw = {
  flagged: true, manual: null,
  reasons: [{ source: "civitai", nsfw: true, tags: [], words: [], level: 8, score: null },
            { source: "metadata", nsfw: true, tags: ["nude"], words: ["lewd"], level: null, score: null }],
};

function model(name: string, overrides: Partial<ModelFile> = {}): ModelFile {
  return {
    folder: "loras", name, size: 1000, modified: 1700000000, family: "Illustrious", family_source: "metadata", triggers: [],
    triggers_source: "", title: "", has_preview: true, preview_origin: "", preview_kind: "image", used_by: [], nsfw: SAFE, ...overrides,
  };
}

function library(models: ModelFile[] = [
  model("clean.safetensors", { used_by: [{ id: "portrait.json", label: "portrait" }] }),
  model("spicy.safetensors", { nsfw: BY_TAGS }),
  model("plain.safetensors", { has_preview: false }),
]): ModelLibrary {
  return {
    folders: [{ name: "loras", count: models.length }],
    models,
    missing: [{ folder: "vae", name: "ae.safetensors", url: "https://huggingface.co/x/y/resolve/main/ae.safetensors",
                workflows: [{ id: "declaring.json", label: "declaring" }] }],
    download: { route: "local", note: "" },
    downloads: [],
    preview_tools: { lookup: "sha256", save: true, save_note: "" },
  };
}

/** 这个连接上的一张工作流(生成选项):有一格选 loras 目录的文件。 */
function workflow(id: string, options: string[]) {
  return {
    id: `p9:image:${id}`, provider_profile_id: "p9", profile_name: "ComfyUI", provider: "plugin:dev.mosael.comfyui",
    kind: "image", model: id, model_label: id.replace(/\.json$/, ""), plugin_instance_id: "i1",
    capabilities: {
      modes: ["text-to-image"], parameter_keys: ["9.lora_name"],
      parameter_schema: { "9.lora_name": { type: "string", title: "lora", enum: options, "x-model-folder": "loras" } },
    },
    capabilities_known: true, adapter_available: true, is_default: false,
  };
}

const clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };

function localNsfw(overrides: Partial<ModelLocalNsfw> = {}): ModelLocalNsfw {
  return { status: "missing", message: "", size_bytes: 22404720, pending: 0, scored: 0, ...overrides };
}

beforeEach(() => {
  window.localStorage.clear();
  for (const fn of Object.values(api)) if (typeof fn === "function" && "mockReset" in fn) (fn as ReturnType<typeof vi.fn>).mockReset();
  handoff.mockReset();
  imagePreview.mockReset();
  clipboard.writeText.mockClear();
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: clipboard });
  Element.prototype.scrollIntoView ??= () => {};
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  api.getModelLibrary.mockResolvedValue(library());
  api.getLocalNsfw.mockResolvedValue(localNsfw());
  authMe.mockResolvedValue({ is_deployment_admin: true });
  api.listGenerationOptions.mockImplementation(async (kind: string) =>
    kind === "image" ? [workflow("portrait.json", ["clean.safetensors", "spicy.safetensors"]),
                        workflow("other.json", ["spicy.safetensors"])] : []);
  api.getModelDetail.mockImplementation(async (_id: string, folder: string, name: string) => ({ folder, name, metadata: {}, tags: [] }));
});

function open() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<ModelLibraryDialog open onOpenChange={() => undefined} instance={instance} workspaceId="w1" />, {
    wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  });
  return screen.findByRole("list", { name: "modelLibraryTitle" });
}

const card = (name: string) =>
  within(screen.getByRole("list", { name: "modelLibraryTitle" })).getAllByRole("listitem").find((one) => one.textContent?.includes(name))!;

function pick(group: "modelPreviewLevel" | "modelPreviewNsfw", option: string) {
  if (!screen.queryByRole("radiogroup", { name: group })) fireEvent.click(screen.getByRole("button", { name: "modelPreviewSettings" }));
  fireEvent.click(within(screen.getByRole("radiogroup", { name: group })).getByRole("radio", { name: option }));
}

const treatment = (name: string) => card(name).querySelector("img")?.getAttribute("data-treatment") ?? "none";

describe("预览图分档、NSFW 单独管", () => {
  it("缺省:平常的清晰、NSFW 的模糊;两组独立、取更严的那一档;不显示的不去取图;记在本机", async () => {
    await open();
    expect(treatment("clean.safetensors")).toBe("clear");
    expect(treatment("spicy.safetensors")).toBe("heavy");

    pick("modelPreviewLevel", "modelPreviewLevelLight");
    expect(treatment("clean.safetensors")).toBe("light");
    expect(treatment("spicy.safetensors"), "NSFW 那一档更严,照它").toBe("heavy");

    pick("modelPreviewNsfw", "modelPreviewNsfwHidden");
    expect(treatment("clean.safetensors")).toBe("light");
    const hidden = card("spicy.safetensors");
    expect(hidden.querySelector("img")).toBeNull();
    expect(hidden.querySelector("[data-hidden-preview]")?.textContent).toContain("modelPreviewHidden");
    expect(JSON.parse(window.localStorage.getItem("mosael:model-previews")!)).toEqual({ level: "light", nsfw: "hidden" });

    pick("modelPreviewNsfw", "modelPreviewNsfwShow");
    expect(treatment("spicy.safetensors"), "照常:和别的预览图一样按「预览图」那一档").toBe("light");
    pick("modelPreviewLevel", "modelPreviewLevelHidden");
    expect(card("clean.safetensors").querySelector("img")).toBeNull();
    expect(card("plain.safetensors").querySelector("[data-hidden-preview]"), "本来就没有预览图的照旧是目录图标").toBeNull();
  });

  it("判成 NSFW 的卡片带一枚角标,悬停说凭什么;没判的不画", async () => {
    await open();
    expect(card("clean.safetensors").querySelector("[data-nsfw-mark]")).toBeNull();
    const mark = card("spicy.safetensors").querySelector<HTMLElement>("[data-nsfw-mark]")!;
    expect(mark.textContent).toBe("modelNsfwBadge");
    const said = await hoverHint(mark);
    expect(said).toContain("modelNsfwAuto");
    expect(said).toContain("modelNsfwCivitaiImage");
    expect(said).toContain("modelNsfwTags");
    expect(said).toContain("modelNsfwWords");
  });

  it("列表里同一套:缩略图照分档画,名字旁边是 NSFW 角标和 ⋯", async () => {
    window.localStorage.setItem("mosael:tab:model-library.density", "list");
    window.localStorage.setItem("mosael:model-previews", JSON.stringify({ level: "clear", nsfw: "hidden" }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<ModelLibraryDialog open onOpenChange={() => undefined} instance={instance} workspaceId="w1" />, {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    });
    const table = await screen.findByRole("table", { name: "modelLibraryTitle" });
    const row = (name: string) => within(table).getAllByRole("row").find((one) => one.textContent?.includes(name))!;
    expect(row("clean.safetensors").querySelector("img")?.getAttribute("data-treatment")).toBe("clear");
    expect(row("spicy.safetensors").querySelector("img")).toBeNull();
    expect(row("spicy.safetensors").querySelector("[data-hidden-preview]")).toBeTruthy();
    expect(row("spicy.safetensors").querySelector("[data-nsfw-mark]")).toBeTruthy();
    expect(within(row("clean.safetensors")).getByRole("button", { name: "modelMenuLabel" })).toBeTruthy();
  });

  it("详情:不显示的点「显示这一张」才取图;NSFW 一行写结论和依据,能标成是 / 不是、改回自动,改了卡片跟着变", async () => {
    window.localStorage.setItem("mosael:model-previews", JSON.stringify({ level: "clear", nsfw: "hidden" }));
    api.markModelNsfw.mockResolvedValueOnce({ flagged: false, manual: false, reasons: BY_TAGS.reasons });
    api.markModelNsfw.mockResolvedValueOnce({ ...BY_TAGS });
    await open();
    fireEvent.click(within(card("spicy.safetensors")).getByRole("button", { name: "spicy.safetensors" }));
    await screen.findByRole("button", { name: "modelLibraryBack" });
    const media = document.querySelector<HTMLElement>("[data-library-detail-pane='media']")!;
    expect(within(media).queryByRole("img")).toBeNull();
    expect(media.textContent).toContain("modelPreviewHiddenNsfw");
    fireEvent.click(within(media).getByRole("button", { name: "modelShowHiddenPreview" }));
    expect(within(media).getByRole("img").getAttribute("data-treatment")).toBe("clear");

    const overview = screen.getByText("modelNsfwRow").closest("div")!;
    expect(overview.textContent).toContain("modelNsfwAuto");
    expect(overview.textContent).toContain("modelNsfwCivitaiImage");
    fireEvent.click(within(overview).getByRole("button", { name: "modelNsfwUnmark" }));
    await waitFor(() => expect(api.markModelNsfw).toHaveBeenCalledWith("i1", { folder: "loras", name: "spicy.safetensors", nsfw: false }));
    await waitFor(() => expect(screen.getByText("modelNsfwRow").closest("div")!.textContent).toContain("modelNsfwManualNo"));
    expect(api.getModelLibrary, "宿主回了新的判断,不让插件再列一遍").toHaveBeenCalledTimes(1);
    fireEvent.click(within(screen.getByText("modelNsfwRow").closest("div")!).getByRole("button", { name: "modelNsfwClearMark" }));
    await waitFor(() => expect(api.markModelNsfw).toHaveBeenLastCalledWith("i1", { folder: "loras", name: "spicy.safetensors", nsfw: null }));
    await waitFor(() => expect(screen.getByText("modelNsfwRow").closest("div")!.textContent).toContain("modelNsfwAuto"));
  });
});

describe("右键菜单", () => {
  const menu = () => screen.getByRole("menu");
  const entry = (key: string) => menu().querySelector<HTMLElement>(`[data-menu-entry="${key}"]`);

  it("右键一张卡:同一份菜单,条目按这个模型的状态出;点不了的写为什么", async () => {
    await open();
    fireEvent.contextMenu(within(card("plain.safetensors")).getByRole("button", { name: "plain.safetensors" }), { clientX: 10, clientY: 10 });
    expect(menu().getAttribute("aria-label")).toBe("modelMenuLabel");
    for (const key of ["open", "generate", "copy-name", "copy-path", "used", "large", "nsfw-on"]) {
      expect(entry(key), key).toBeTruthy();
    }
    expect(entry("nsfw-off")).toBeNull();
    expect(entry("nsfw-auto"), "没手动标过,就没有「改回自动判断」").toBeNull();
    //: 没有预览图、没有工作流在用、没有工作流能选它:点不了,名字下面一行写为什么
    expect(entry("large")!.getAttribute("aria-disabled")).toBe("true");
    expect(entry("large")!.textContent).toContain("modelNoPreview");
    expect(entry("used")!.getAttribute("aria-disabled")).toBe("true");
    expect(entry("used")!.textContent).toContain("modelUsedByNone");
    await waitFor(() => expect(api.listGenerationOptions).toHaveBeenCalled());
    expect(entry("generate")!.textContent).toMatch(/modelUseToGenerate(None|Loading)/);
    expect(entry("copy-path")!.textContent).toContain("loras/plain.safetensors");
    expect(entry("lookup")!.textContent, "没有预览图的:去 Civitai 找一张来").toContain("modelLookupPreview");
    fireEvent.keyDown(menu(), { key: "Escape" });
    //: 有预览图的(哪怕还说不准是哪儿的):去 Civitai 上找的是出处、NSFW 标记
    fireEvent.contextMenu(within(card("clean.safetensors")).getByRole("button", { name: "clean.safetensors" }), { clientX: 10, clientY: 10 });
    expect(entry("lookup")!.textContent).toMatch(/modelLookup(?!Preview)/);
  });

  it("条目各做各的事:打开详情、复制、在用的工作流跳到那一节、大图交给共用灯箱(能翻当前筛出来的)、标 NSFW", async () => {
    api.markModelNsfw.mockResolvedValue({ flagged: true, manual: true, reasons: [] });
    await open();
    const target = () => within(card("clean.safetensors")).getByRole("button", { name: "clean.safetensors" });

    fireEvent.contextMenu(target(), { clientX: 10, clientY: 10 });
    fireEvent.click(entry("copy-path")!);
    expect(clipboard.writeText).toHaveBeenCalledWith("loras/clean.safetensors");

    fireEvent.contextMenu(target(), { clientX: 10, clientY: 10 });
    fireEvent.click(entry("large")!);
    expect(imagePreview).toHaveBeenCalledTimes(1);
    const shown = imagePreview.mock.calls[0][0];
    expect(shown.src).toBe("preview://i1/loras/clean.safetensors");
    expect(shown.gallery.map((one: { src: string }) => one.src), "没有预览图的、模糊着的(spicy 是 NSFW)不进画廊").toEqual([
      "preview://i1/loras/clean.safetensors",
    ]);
    //: 点的是模糊着的那一张:明确要看它,画廊里只有它
    fireEvent.contextMenu(within(card("spicy.safetensors")).getByRole("button", { name: "spicy.safetensors" }), { clientX: 10, clientY: 10 });
    fireEvent.click(entry("large")!);
    expect(imagePreview.mock.calls[1][0].gallery.map((one: { src: string }) => one.src)).toEqual(["preview://i1/loras/spicy.safetensors"]);

    fireEvent.contextMenu(target(), { clientX: 10, clientY: 10 });
    fireEvent.click(entry("nsfw-on")!);
    await waitFor(() => expect(api.markModelNsfw).toHaveBeenCalledWith("i1", { folder: "loras", name: "clean.safetensors", nsfw: true }));
    await waitFor(() => expect(card("clean.safetensors").querySelector("[data-nsfw-mark]")).toBeTruthy());

    fireEvent.contextMenu(target(), { clientX: 10, clientY: 10 });
    expect(entry("nsfw-off")).toBeTruthy();
    expect(entry("nsfw-auto"), "手动标过:能改回自动判断").toBeTruthy();
    fireEvent.click(entry("used")!);
    expect(await screen.findByRole("button", { name: "modelLibraryBack" })).toBeTruthy();
  });

  it("「用它生成」:一张工作流能选就直接交;几张就在子菜单里挑", async () => {
    await open();
    await waitFor(() => expect(api.listGenerationOptions).toHaveBeenCalled());
    fireEvent.contextMenu(within(card("clean.safetensors")).getByRole("button", { name: "clean.safetensors" }), { clientX: 10, clientY: 10 });
    await waitFor(() => expect(entry("generate")!.getAttribute("aria-disabled")).not.toBe("true"));
    fireEvent.click(entry("generate")!);
    expect(handoff).toHaveBeenCalledWith(expect.objectContaining({ model: "portrait.json", declared: { "9.lora_name": "clean.safetensors" } }));

    fireEvent.contextMenu(within(card("spicy.safetensors")).getByRole("button", { name: "spicy.safetensors" }), { clientX: 10, clientY: 10 });
    const sub = within(menu()).getByRole("menuitem", { name: /modelUseToGenerate/ });
    expect(sub.getAttribute("aria-haspopup")).toBe("menu");
    //: 像鼠标那样移到「用它生成」上:子菜单打开,列出这个连接上能选它的几张工作流
    fireEvent.pointerMove(sub, { pointerType: "mouse" });
    const submenu = await waitFor(() => {
      const found = Array.from(document.querySelectorAll<HTMLElement>('[role="menu"]'))
        .find((one) => !one.querySelector('[aria-haspopup="menu"]'));
      expect(found).toBeTruthy();
      return found!;
    });
    expect(within(submenu).getAllByRole("menuitem").map((one) => one.textContent)).toEqual(["other", "portrait"]);
    fireEvent.click(within(submenu).getByRole("menuitem", { name: /other/ }));
    expect(handoff).toHaveBeenLastCalledWith(expect.objectContaining({ model: "other.json" }));
  });

  it("卡片上的 ⋯ 和 Shift+F10 打开的是同一个菜单;Esc 关上之后焦点回到打开它的地方", async () => {
    await open();
    const more = within(card("clean.safetensors")).getByRole("button", { name: "modelMenuLabel" });
    expect(more.getAttribute("aria-haspopup")).toBe("menu");
    fireEvent.click(more);
    expect(menu().getAttribute("aria-label")).toBe("modelMenuLabel");
    expect(entry("open")).toBeTruthy();
    fireEvent.keyDown(menu(), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(more));

    const name = within(card("spicy.safetensors")).getByRole("button", { name: "spicy.safetensors" });
    act(() => name.focus());
    fireEvent.keyDown(name, { key: "F10", shiftKey: true });
    expect(entry("nsfw-off"), "这一张判成了 NSFW:菜单里是「标为不是 NSFW」").toBeTruthy();
    fireEvent.keyDown(menu(), { key: "Escape" });
    await waitFor(() => expect(document.activeElement).toBe(name));
    fireEvent.keyDown(name, { key: "ContextMenu" });
    expect(screen.getByRole("menu")).toBeTruthy();
  });

  it("工作流缺的模型那一页:右键能下载(下载框带着地址、目录、文件名)、复制名字和下载地址", async () => {
    await open();
    fireEvent.click(within(screen.getByRole("tablist", { name: "modelLibraryFolders" })).getByRole("tab", { name: "modelMissingTitle 1" }));
    const row = await waitFor(() => document.querySelector<HTMLElement>("[data-missing-item]")!);
    fireEvent.contextMenu(row, { clientX: 10, clientY: 10 });
    fireEvent.click(within(menu()).getByRole("menuitem", { name: /modelMissingCopyLink/ }));
    expect(clipboard.writeText).toHaveBeenCalledWith("https://huggingface.co/x/y/resolve/main/ae.safetensors");
    fireEvent.contextMenu(row, { clientX: 10, clientY: 10 });
    fireEvent.click(within(menu()).getByRole("menuitem", { name: /modelMissingMenuDownload/ }));
    expect(((await screen.findByPlaceholderText("modelDownloadLinkPlaceholder")) as HTMLInputElement).value)
      .toBe("https://huggingface.co/x/y/resolve/main/ae.safetensors");
  });
});


describe("Civitai 的示例图、原链接", () => {
  const FROM_CIVITAI = model("from-civitai.safetensors", {
    preview_origin: "civitai",
    source: { page: "https://civitai.com/models/795765?modelVersionId=889818", site: "civitai", how: "sha256" },
  });
  const BY_NAME = model("by-name.safetensors", {
    preview_origin: "civitai",
    source: { page: "https://civitai.com/models/1?modelVersionId=2", site: "civitai", how: "filename" },
  });
  const job = (id: string, payload: Record<string, unknown>, status = "running") =>
    ({ id, kind: "model_previews", status, payload, progress: 0.1, message: "", result: {} });
  const menu = () => screen.getByRole("menu");
  const entry = (key: string) => menu().querySelector<HTMLElement>(`[data-menu-entry="${key}"]`);

  beforeEach(() => {
    api.getModelLibrary.mockResolvedValue(library([FROM_CIVITAI, BY_NAME, model("on-server.safetensors", { preview_origin: "server" })]));
  });

  it("卡片角上标「来自 Civitai」,悬停说只在 Mosael 里显示;那台服务器上的不标", async () => {
    await open();
    const mark = card("from-civitai.safetensors").querySelector<HTMLElement>("[data-preview-origin='civitai']")!;
    expect(mark.textContent).toBe("Civitai");
    expect(await hoverHint(mark)).toContain("modelPreviewFromSiteHint");
    expect(card("on-server.safetensors").querySelector("[data-preview-origin]")).toBeNull();
  });

  it("「存为预览图」先确认,写明哪台服务器、哪个目录;确认了才写,按当前的挑法", async () => {
    api.saveModelPreview.mockResolvedValue({ folder: "loras", name: "from-civitai.safetensors", saved: "loras/from-civitai.png" });
    await open();
    fireEvent.contextMenu(within(card("from-civitai.safetensors")).getByRole("button", { name: "from-civitai.safetensors" }),
                         { clientX: 10, clientY: 10 });
    fireEvent.click(entry("save-preview")!);
    const confirm = await screen.findByRole("alertdialog");
    expect(confirm.textContent).toContain("modelSavePreviewBody");
    expect(confirm.textContent).not.toContain("modelSavePreviewBodyVideo");
    expect(confirm.textContent).not.toContain("modelSavePreviewFilenameMatch");
    expect(api.saveModelPreview).not.toHaveBeenCalled();
    fireEvent.click(within(confirm).getByRole("button", { name: "modelSavePreview" }));
    await waitFor(() => expect(api.saveModelPreview).toHaveBeenCalledWith("i1", {
      folder: "loras", name: "from-civitai.safetensors", pick: "safest", confirmed: false,
    }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    await waitFor(() => expect(api.getModelLibrary, "存回之后重新列:预览图换成那台服务器上的").toHaveBeenCalledTimes(2));
  });

  it("卡片的缩略图还在取(第一次露面的 Civitai 视频要先取视频、抽第一帧):框里是加载占位,不是一块空白", async () => {
    await open();
    const frame = card("from-civitai.safetensors").querySelector<HTMLElement>("[data-card-thumb]")!;
    expect(frame.querySelector("[data-thumb-loading].skeleton")).not.toBeNull();
    fireEvent.load(frame.querySelector("img")!);
    expect(frame.querySelector("[data-thumb-loading]"), "载好了:撤掉").toBeNull();
  });

  it("示例是一段视频:按钮的说明、确认框都照实说写的是视频、ComfyUI 自己看不到 —— 不说「512 宽的图」「ComfyUI 里也看得到」", async () => {
    const CLIP = model("clip-only.safetensors", { preview_origin: "civitai", preview_kind: "video",
      source: { page: "https://civitai.com/models/153022?modelVersionId=171354", site: "civitai", how: "download" } });
    api.getModelLibrary.mockResolvedValue(library([CLIP, FROM_CIVITAI]));
    await open();
    fireEvent.click(within(card("clip-only.safetensors")).getByRole("button", { name: "clip-only.safetensors" }));
    await screen.findByRole("button", { name: "modelLibraryBack" });
    const media = document.querySelector<HTMLElement>("[data-library-detail-pane='media']")!;
    const button = within(media).getByRole("button", { name: "modelSavePreview" });
    expect(await hoverHint(button)).toContain("modelSavePreviewHintVideo");
    fireEvent.click(button);
    const confirm = await screen.findByRole("alertdialog");
    expect(confirm.textContent).toContain("modelSavePreviewBodyVideo");
    //: 图的那一份是另一个键(「modelSavePreviewBody」是视频那一份的前缀,按整段去掉视频那一份再查)
    expect(confirm.textContent!.replace("modelSavePreviewBodyVideo", "")).not.toContain("modelSavePreviewBody");
  });

  it("按文件名对上的:确认框多说一句「不一定是同一个文件」,确认了才带 confirmed", async () => {
    api.saveModelPreview.mockResolvedValue({ folder: "loras", name: "by-name.safetensors", saved: "loras/by-name.png" });
    await open();
    fireEvent.click(within(card("by-name.safetensors")).getByRole("button", { name: "by-name.safetensors" }));
    await screen.findByRole("button", { name: "modelLibraryBack" });
    const media = document.querySelector<HTMLElement>("[data-library-detail-pane='media']")!;
    fireEvent.click(within(media).getByRole("button", { name: "modelSavePreview" }));
    const confirm = await screen.findByRole("alertdialog");
    expect(confirm.textContent).toContain("modelSavePreviewFilenameMatch");
    fireEvent.click(within(confirm).getByRole("button", { name: "modelSavePreview" }));
    await waitFor(() => expect(api.saveModelPreview).toHaveBeenCalledWith("i1", expect.objectContaining({ confirmed: true })));
  });

  it("写不回(没装 ComfyUI-Custom-Scripts):存为预览图、补图都点不了,说缺什么", async () => {
    api.getModelLibrary.mockResolvedValue({ ...library([FROM_CIVITAI]), preview_tools: { lookup: "filename", save: false, save_note: "缺 ComfyUI-Custom-Scripts" } });
    await open();
    const fill = screen.getByRole("button", { name: "modelFillPreviews" }) as HTMLButtonElement;
    expect(fill.disabled).toBe(true);
    expect(await readHint(fill)).toContain("缺 ComfyUI-Custom-Scripts");
    fireEvent.contextMenu(within(card("from-civitai.safetensors")).getByRole("button", { name: "from-civitai.safetensors" }),
                         { clientX: 10, clientY: 10 });
    expect(entry("save-preview")!.getAttribute("aria-disabled")).toBe("true");
    expect(entry("save-preview")!.textContent).toContain("缺 ComfyUI-Custom-Scripts");
    expect(entry("lookup")!.getAttribute("aria-disabled"), "按文件名还能找").not.toBe("true");
  });

  it("「为缺预览图的模型补图」:先确认,是一个后台任务;做完重新列一遍", async () => {
    api.startModelLookup.mockResolvedValue(job("j9", { save: true, files: [] }));
    api.getModelLookup.mockResolvedValue({ job: job("j9", { save: true, files: [] }, "succeeded"), result: { found: [] } });
    await open();
    fireEvent.click(screen.getByRole("button", { name: "modelFillPreviews" }));
    const confirm = await screen.findByRole("alertdialog");
    expect(confirm.textContent).toContain("modelFillPreviewsBody");
    fireEvent.click(within(confirm).getByRole("button", { name: "modelFillPreviewsStart" }));
    await waitFor(() => expect(api.startModelLookup).toHaveBeenCalledWith("i1", { workspace_id: "w1", save: true, pick: "safest" }));
    await waitFor(() => expect(api.getModelLookup).toHaveBeenCalledWith("i1", "j9"), { timeout: 3000 });
    await waitFor(() => expect(api.getModelLibrary).toHaveBeenCalledTimes(2), { timeout: 3000 });
  });

  it("「为缺预览图的模型补图」:确认之后工具条上那颗转圈,一直转到补图任务做完", async () => {
    let finished = false;
    api.startModelLookup.mockResolvedValue(job("j10", { save: true, files: [] }));
    api.getModelLookup.mockImplementation(async () => (finished
      ? { job: job("j10", { save: true, files: [] }, "succeeded"), result: { found: [] } }
      : { job: job("j10", { save: true, files: [] }), result: null }));
    await open();
    const fill = () => screen.getByRole("button", { name: "modelFillPreviews" }) as HTMLButtonElement;
    fireEvent.click(fill());
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "modelFillPreviewsStart" }));
    await waitFor(() => expect(fill().getAttribute("aria-busy")).toBe("true"));
    expect(fill().querySelector("svg.animate-mosael-spin")).not.toBeNull();
    await waitFor(() => expect(api.getModelLookup).toHaveBeenCalledWith("i1", "j10"), { timeout: 3000 });
    expect(fill().getAttribute("aria-busy"), "任务还在跑:接着转").toBe("true");
    finished = true;
    await waitFor(() => expect(fill().getAttribute("aria-busy")).toBeNull(), { timeout: 4000 });
    expect(fill().disabled).toBe(false);
  });

  it("「存为预览图」:存的时候那颗按钮转圈;存好了它和「来自 Civitai」当场撤掉,不等重列回来", async () => {
    let saved: (value: unknown) => void = () => undefined;
    api.saveModelPreview.mockReturnValue(new Promise((resolve) => { saved = resolve; }));
    api.getModelLibrary.mockResolvedValueOnce(library([FROM_CIVITAI])).mockImplementation(() => new Promise(() => undefined));
    await open();
    fireEvent.click(within(card("from-civitai.safetensors")).getByRole("button", { name: "from-civitai.safetensors" }));
    await screen.findByRole("button", { name: "modelLibraryBack" });
    const media = () => document.querySelector<HTMLElement>("[data-library-detail-pane='media']")!;
    fireEvent.click(within(media()).getByRole("button", { name: "modelSavePreview" }));
    const confirm = await screen.findByRole("alertdialog");
    fireEvent.click(within(confirm).getByRole("button", { name: "modelSavePreview" }));
    await waitFor(() => expect(within(media()).getByRole("button", { name: "modelSavePreview", hidden: true })
      .getAttribute("aria-busy")).toBe("true"));
    await act(async () => saved({ folder: "loras", name: "from-civitai.safetensors", saved: "loras/from-civitai.png" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(within(media()).queryByRole("button", { name: "modelSavePreview" }), "存好了:没有可存的了").toBeNull();
    expect(media().querySelector("[data-preview-origin='civitai']"), "预览图已经是那台服务器上的").toBeNull();
    expect(api.getModelLibrary, "重列还在后台跑(这里永远回不来)").toHaveBeenCalledTimes(2);
  });

  it("详情:原链接点开是原站那一页,下面说怎么知道的;没有的说没有,「在 Civitai 上找」起一个任务、找的时候点不了", async () => {
    api.startModelLookup.mockResolvedValue(job("j1", { files: [{ folder: "loras", name: "on-server.safetensors" }] }));
    api.getModelLookup.mockResolvedValue({ job: job("j1", { files: [{ folder: "loras", name: "on-server.safetensors" }] }), result: null });
    await open();
    fireEvent.click(within(card("from-civitai.safetensors")).getByRole("button", { name: "from-civitai.safetensors" }));
    await screen.findByRole("button", { name: "modelLibraryBack" });
    const link = document.querySelector<HTMLAnchorElement>("[data-model-source]")!;
    expect(link.href).toBe("https://civitai.com/models/795765?modelVersionId=889818");
    expect(link.target).toBe("_blank");
    expect(screen.getByText("modelSourceRow").closest("div")!.textContent).toContain("modelSourceHowSha256");
    fireEvent.click(screen.getByRole("button", { name: "modelLibraryBack" }));

    fireEvent.click(within(await waitFor(() => card("on-server.safetensors"))).getByRole("button", { name: "on-server.safetensors" }));
    await screen.findByRole("button", { name: "modelLibraryBack" });
    const row = screen.getByText("modelSourceRow").closest("div")!;
    expect(row.textContent).toContain("modelSourceUnknown");
    expect(row.textContent).toContain("modelSourceNone");
    fireEvent.click(within(row).getByRole("button", { name: /modelLookup/ }));
    await waitFor(() => expect(api.startModelLookup).toHaveBeenCalledWith("i1", {
      workspace_id: "w1", files: [{ folder: "loras", name: "on-server.safetensors" }], refresh: true, pick: "safest",
    }));
    await waitFor(() => expect((within(screen.getByText("modelSourceRow").closest("div")!).getByRole("button", { name: /modelLookup/ }) as HTMLButtonElement).disabled).toBe(true));
  });

  it("「在 Civitai 上找」:点下去就转圈(不只是变灰),一直转到任务做完 —— 不是发起任务的那个请求一回来就停", async () => {
    //: 维护者:点了之后没有 loading,只是 disable 了。那一趟要那台机器把整个文件读一遍,好一阵什么都看不出来。
    const files = [{ folder: "loras", name: "on-server.safetensors" }];
    let created: (value: unknown) => void = () => undefined;
    api.startModelLookup.mockReturnValue(new Promise((resolve) => { created = resolve; }));
    let finished = false;
    api.getModelLookup.mockImplementation(async () => (finished
      ? { job: job("j7", { files }, "succeeded"), result: { found: [] } }
      : { job: job("j7", { files }), result: null }));
    await open();
    fireEvent.click(within(card("on-server.safetensors")).getByRole("button", { name: "on-server.safetensors" }));
    await screen.findByRole("button", { name: "modelLibraryBack" });
    const find = () => within(screen.getByText("modelSourceRow").closest("div")!).getByRole("button", { name: /modelLookup/ }) as HTMLButtonElement;
    expect(find().getAttribute("aria-busy")).toBeNull();
    fireEvent.click(find());

    await waitFor(() => expect(find().getAttribute("aria-busy"), "发起任务的请求还没回来:已经在转").toBe("true"));
    expect(find().disabled).toBe(true);
    expect(find().querySelector("svg.animate-mosael-spin"), "图标换成转圈").not.toBeNull();
    expect(await readHint(find()), "说明里照旧写为什么点不了").toContain("modelLookupRunning");

    await act(async () => created(job("j7", { files })));
    await waitFor(() => expect(api.getModelLookup).toHaveBeenCalledWith("i1", "j7"), { timeout: 3000 });
    expect(find().getAttribute("aria-busy"), "任务还在跑:接着转").toBe("true");

    finished = true;
    await waitFor(() => expect(find().getAttribute("aria-busy"), "任务做完:不转了").toBeNull(), { timeout: 4000 });
    expect(find().disabled, "做完能再找一次").toBe(false);
    expect(find().querySelector("svg.animate-mosael-spin")).toBeNull();
  });

  it("右键菜单里找:菜单关上;正在找时再打开,这一行点不了、写着进度在任务中心、图标在转", async () => {
    const files = [{ folder: "loras", name: "on-server.safetensors" }];
    api.startModelLookup.mockResolvedValue(job("j8", { files }));
    api.getModelLookup.mockResolvedValue({ job: job("j8", { files }), result: null });
    await open();
    const opener = () => within(card("on-server.safetensors")).getByRole("button", { name: "on-server.safetensors" });
    fireEvent.contextMenu(opener(), { clientX: 10, clientY: 10 });
    fireEvent.click(entry("lookup")!);
    await waitFor(() => expect(api.startModelLookup).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    fireEvent.contextMenu(opener(), { clientX: 10, clientY: 10 });
    await waitFor(() => expect(entry("lookup")!.getAttribute("aria-disabled")).toBe("true"));
    expect(entry("lookup")!.textContent).toContain("modelLookupRunning");
    expect(entry("lookup")!.querySelector("svg.animate-mosael-spin")).not.toBeNull();
  });

  it("「在 Civitai 上找」做完:原链接和 Civitai 那张示例图当场就有,不等整份重列", async () => {
    //: 维护者:找到之后详情里的原链接要过好一阵才出来 —— 此前要等任务做完再整份重列(几百个模型的服务器上好几秒)。
    //: 这里让重列永远回不来:原链接照样出来,靠的是任务交回的那一条(`found`)当场改进记着的模型库。
    //: 和真的一样:新版 ComfyUI 给每个文件都报预览地址(has_preview),取了才知道没有(404)
    const PLAIN = model("plain.safetensors", { preview_origin: "" });
    api.getModelLibrary.mockResolvedValueOnce(library([PLAIN])).mockImplementation(() => new Promise(() => undefined));
    const files = [{ folder: "loras", name: "plain.safetensors" }];
    api.startModelLookup.mockResolvedValue(job("j2", { files }));
    api.getModelLookup.mockResolvedValue({
      job: job("j2", { files }, "succeeded"),
      result: { found: [{
        folder: "loras", name: "plain.safetensors", match: "sha256",
        source: { page: "https://civitai.com/models/58390?modelVersionId=62833", site: "civitai", how: "sha256" },
        has_preview: true, preview_origin: "civitai", preview_kind: "image", nsfw: SAFE,
      }] },
    });
    await open();
    fireEvent.click(within(card("plain.safetensors")).getByRole("button", { name: "plain.safetensors" }));
    await screen.findByRole("button", { name: "modelLibraryBack" });
    expect(document.querySelector("[data-model-source]")).toBeNull();
    const pane = () => document.querySelector<HTMLElement>("[data-library-detail-pane='media']")!;
    fireEvent.error(pane().querySelector("img")!);
    expect(pane().querySelector("img"), "那台服务器上没有:换成占位").toBeNull();
    fireEvent.click(within(screen.getByText("modelSourceRow").closest("div")!).getByRole("button", { name: /modelLookup/ }));
    const link = await waitFor(() => {
      const found = document.querySelector<HTMLAnchorElement>("[data-model-source]");
      expect(found).not.toBeNull();
      return found!;
    }, { timeout: 3000 });
    expect(link.href).toBe("https://civitai.com/models/58390?modelVersionId=62833");
    expect(pane().querySelector("[data-preview-origin='civitai']"), "预览图换成 Civitai 那张,角上标出来").not.toBeNull();
    expect(pane().querySelector("img")?.getAttribute("src"), "刚才没取到的那张不算数:从哪来变了,再取一次")
      .toBe("preview://i1/loras/plain.safetensors");
    expect(api.getModelLibrary, "重列还在后台跑(这里永远回不来)").toHaveBeenCalledTimes(2);
  });

  it("在卡片的右键菜单里找:卡片一直开着,刚才没取到的缩略图在找到之后换上 Civitai 那张", async () => {
    const PLAIN = model("plain.safetensors", { preview_origin: "" });
    api.getModelLibrary.mockResolvedValueOnce(library([PLAIN])).mockImplementation(() => new Promise(() => undefined));
    const files = [{ folder: "loras", name: "plain.safetensors" }];
    api.startModelLookup.mockResolvedValue(job("j3", { files }));
    api.getModelLookup.mockResolvedValue({
      job: job("j3", { files }, "succeeded"),
      result: { found: [{
        folder: "loras", name: "plain.safetensors", match: "sha256", source: null,
        has_preview: true, preview_origin: "civitai", preview_kind: "image", nsfw: SAFE,
      }] },
    });
    await open();
    fireEvent.error(card("plain.safetensors").querySelector("img")!);
    expect(card("plain.safetensors").querySelector("img"), "那台服务器上没有:卡片换成占位").toBeNull();
    fireEvent.contextMenu(within(card("plain.safetensors")).getByRole("button", { name: "plain.safetensors" }),
                         { clientX: 10, clientY: 10 });
    fireEvent.click(entry("lookup")!);
    await waitFor(() => expect(card("plain.safetensors").querySelector("[data-preview-origin='civitai']")).not.toBeNull(),
                  { timeout: 3000 });
    expect(card("plain.safetensors").querySelector("img")?.getAttribute("src"), "从哪来变了:再取一次")
      .toBe("thumbnail://i1/loras/plain.safetensors");
  });

  it("右键菜单:有原链接的「打开原链接」在浏览器里开;没有的不摆", async () => {
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    await open();
    fireEvent.contextMenu(within(card("from-civitai.safetensors")).getByRole("button", { name: "from-civitai.safetensors" }),
                         { clientX: 10, clientY: 10 });
    fireEvent.click(entry("source")!);
    expect(opened).toHaveBeenCalledWith("https://civitai.com/models/795765?modelVersionId=889818", "_blank", "noopener,noreferrer");
    fireEvent.contextMenu(within(card("on-server.safetensors")).getByRole("button", { name: "on-server.safetensors" }),
                         { clientX: 10, clientY: 10 });
    expect(entry("source")).toBeNull();
    expect(entry("save-preview"), "预览图本来就在那台服务器上:没有可存的").toBeNull();
    expect(entry("lookup")!.textContent).toContain("modelLookup");
    opened.mockRestore();
  });
});


describe("预览视频", () => {
  const CLIP = model("clip.safetensors", { preview_kind: "video", preview_origin: "civitai" });

  beforeEach(() => {
    api.getModelLibrary.mockResolvedValue(library([CLIP, model("still.safetensors")]));
  });

  it("卡片上是第一帧;鼠标移上去静音循环播,移开停;模糊着不播", async () => {
    await open();
    const clip = card("clip.safetensors");
    const article = clip.querySelector<HTMLElement>("[data-library-item]")!;
    expect(clip.querySelector("img")!.getAttribute("src")).toContain("thumbnail://");
    expect(clip.querySelector("video")).toBeNull();
    fireEvent.pointerEnter(article);
    const video = clip.querySelector<HTMLVideoElement>("[data-preview-video]")!;
    expect(video.getAttribute("src")).toBe("preview://i1/loras/clip.safetensors");
    expect(video.muted && video.loop && video.autoplay).toBe(true);
    fireEvent.pointerLeave(article);
    expect(clip.querySelector("video")).toBeNull();
    fireEvent.pointerEnter(within(card("still.safetensors")).getByRole("button", { name: "still.safetensors" }).closest("article")!);
    expect(card("still.safetensors").querySelector("video"), "图不是视频:没有可播的").toBeNull();

    pick("modelPreviewLevel", "modelPreviewLevelLight");
    fireEvent.pointerEnter(article);
    expect(clip.querySelector("video"), "模糊着自己动起来等于没糊:不播").toBeNull();
  });

  it("详情里能播(全站的播放器、静音、循环,不是浏览器自带的控件条);模糊着先是第一帧,点「看清」才是视频", async () => {
    await open();
    fireEvent.click(within(card("clip.safetensors")).getByRole("button", { name: "clip.safetensors" }));
    await screen.findByRole("button", { name: "modelLibraryBack" });
    const media = () => document.querySelector<HTMLElement>("[data-library-detail-pane='media']")!;
    const player = media().querySelector<HTMLVideoElement>("[data-detail-video] video")!;
    expect(player.muted && player.loop).toBe(true);
    expect(player.controls).toBe(false);
    expect(within(media()).getByRole("button", { name: "boardUnmute" })).toBeInTheDocument();
    expect(player.autoplay).toBe(false);
    expect(player.getAttribute("poster")).toBe("thumbnail://i1/loras/clip.safetensors");
    fireEvent.click(screen.getByRole("button", { name: "modelLibraryBack" }));

    window.localStorage.setItem("mosael:model-previews", JSON.stringify({ level: "heavy", nsfw: "blur" }));
    window.dispatchEvent(new Event("mosael:model-previews-changed"));
    fireEvent.click(within(await waitFor(() => card("clip.safetensors"))).getByRole("button", { name: "clip.safetensors" }));
    await screen.findByRole("button", { name: "modelLibraryBack" });
    expect(media().querySelector("video")).toBeNull();
    expect(media().querySelector("img")!.getAttribute("src")).toContain("thumbnail://");
    fireEvent.click(within(media()).getByRole("button", { name: "modelRevealPreview" }));
    expect(media().querySelector("[data-detail-video]")).toBeTruthy();
  });

  it("「查看大图」交给共用灯箱时,视频那一项按视频放", async () => {
    await open();
    fireEvent.contextMenu(within(card("clip.safetensors")).getByRole("button", { name: "clip.safetensors" }), { clientX: 10, clientY: 10 });
    fireEvent.click(screen.getByRole("menu").querySelector<HTMLElement>('[data-menu-entry="large"]')!);
    const shown = imagePreview.mock.calls[0][0];
    expect(shown.video).toBe(true);
    expect(shown.gallery.map((one: { video?: boolean }) => Boolean(one.video))).toEqual([true, false]);
  });
});


describe("本机识别", () => {
  const row = () => screen.getByRole("region", { name: "modelLocalNsfw" });

  it("预览图设置里一行:没下就写多大、点了才下(部署管理员);下着时转圈;下好了说识别到哪儿", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "modelPreviewSettings" }));
    await waitFor(() => expect(row().textContent).toContain("modelLocalNsfwHint"));
    api.installLocalNsfw.mockResolvedValue(localNsfw({ status: "installing" }));
    api.getLocalNsfw.mockResolvedValue(localNsfw({ status: "installing" }));
    fireEvent.click(await within(row()).findByRole("button", { name: /modelLocalNsfwDownload/ }));
    await waitFor(() => expect(api.installLocalNsfw).toHaveBeenCalledTimes(1));
    expect(await within(row()).findByRole("button", { name: /modelLocalNsfwInstalling/ })).toHaveProperty("disabled", true);

    //: 下好了:模型库重新列一遍(排进识别的那一批要靠这一次列)
    const listed = api.getModelLibrary.mock.calls.length;
    api.getLocalNsfw.mockResolvedValue(localNsfw({ status: "installed", pending: 3 }));
    await waitFor(() => expect(row().textContent).toContain("modelLocalNsfwPending"), { timeout: 4000 });
    await waitFor(() => expect(api.getModelLibrary.mock.calls.length).toBeGreaterThan(listed));
    //: 排着的识别完了:再列一遍,结果出现在卡片上
    const again = api.getModelLibrary.mock.calls.length;
    api.getLocalNsfw.mockResolvedValue(localNsfw({ status: "installed", pending: 0, scored: 3 }));
    await waitFor(() => expect(row().textContent).toContain("modelLocalNsfwReady"), { timeout: 4000 });
    await waitFor(() => expect(api.getModelLibrary.mock.calls.length).toBeGreaterThan(again));
  });

  it("不是部署管理员:不给下载按钮,说要谁来下", async () => {
    authMe.mockResolvedValue({ is_deployment_admin: false });
    await open();
    fireEvent.click(screen.getByRole("button", { name: "modelPreviewSettings" }));
    await waitFor(() => expect(row().textContent).toContain("modelLocalNsfwAdminOnly"));
    expect(within(row()).queryByRole("button")).toBeNull();
  });

  it("下失败了写原因、能重试", async () => {
    api.getLocalNsfw.mockResolvedValue(localNsfw({ status: "failed", message: "SHA-256 不对" }));
    await open();
    fireEvent.click(screen.getByRole("button", { name: "modelPreviewSettings" }));
    expect((await within(row()).findByRole("alert")).textContent).toContain("modelLocalNsfwFailed");
    expect(await within(row()).findByRole("button", { name: /modelLocalNsfwRetry/ })).toBeTruthy();
    //: 体检 UM-16:下不下来多半是网络 —— 给一条去换模型下载源的路(管理 → 引擎 → 下载源)。
    const hash = window.location.hash;
    fireEvent.click(within(row()).getByRole("button", { name: /modelLocalNsfwChangeSource/ }));
    expect(window.location.hash).toBe("#/admin");
    window.location.hash = hash;
  });

  it("本机识别那一条依据:悬停写 NSFW 的可能是几成", async () => {
    api.getModelLibrary.mockResolvedValue(library([
      model("spicy.safetensors", { nsfw: { flagged: true, manual: null, reasons: [{ source: "local", nsfw: true, score: 0.87 }] } as ModelNsfw }),
    ]));
    await open();
    const mark = card("spicy.safetensors").querySelector("[data-nsfw-mark]")!;
    expect(mark.getAttribute("aria-label")).toContain("modelNsfwLocal");
  });
});
