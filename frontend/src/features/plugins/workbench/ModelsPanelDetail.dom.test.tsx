/** @vitest-environment jsdom */

/**
 * 工作台「模型库」那一列里看一个模型的详情(维护者:「右侧这个 side 的模型卡片要支持查看详情信息,就像模型库的模型卡片点击后的
 * 详情弹窗那样」):
 *
 * - 每一行悬停 / 聚焦时露出「查看详情」(键盘 Tab 得到),右键是模型库那一份菜单、第一项「查看详情」;点一行本身照旧是填进画布;
 * - 详情就是模型库点开一张卡的那一页(同一个 ModelDetail、同一份本事:NSFW 标记、在 Civitai 上找……),开成一个大弹窗,
 *   压在外壳之上;开着的时候画布(原生视图)让开 —— 先铺一张冻结的画面再挪开 —— 关上放回;焦点回到那一行;
 * - 预览图照模型库那两组设置(模糊、NSFW)。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getNodeFolders: vi.fn(),
  getModelLibrary: vi.fn(),
  getModelDetail: vi.fn(),
  getLocalNsfw: vi.fn(),
  installLocalNsfw: vi.fn(),
  markModelNsfw: vi.fn(),
  saveModelPreview: vi.fn(),
  startModelLookup: vi.fn(),
  getModelLookup: vi.fn(),
  resolveModelLink: vi.fn(),
  searchModelSources: vi.fn(),
  startModelDownload: vi.fn(),
  getJob: vi.fn(),
  cancelJob: vi.fn(),
  listGenerationOptions: vi.fn(),
  modelPreviewUrl: (_: string, folder: string, name: string) => `preview://${folder}/${name}`,
  modelThumbnailUrl: (_: string, folder: string, name: string) => `thumb://${folder}/${name}`,
}));
vi.mock("@/api/client", () => api);
vi.mock("@/api/domains/generation", () => ({ listGenerationOptions: api.listGenerationOptions }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh" }) }));

import type { ModelFile, ModelNsfw } from "@/api/client";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { ModalShell } from "@/components/app/modals";
import { APP_CHROME, installAppChromeGuards } from "@/components/ui/appChrome";
import { NativeViewStandIn, resetNativeViewAside } from "@/components/ui/nativeViewAside";
import { HintRegion } from "@/components/ui/tooltip";
import { ModelsPanel } from "./ModelsPanel";
import { openWorkbench, resetWorkbench } from "./workbenchSession";

const TARGET = { instanceId: "i1", instanceName: "ComfyUI · 192.168.3.15", workspaceId: "w1", url: "http://192.168.3.15:8188" };
const CAPS = { selection: true, setWidget: true, refreshCombos: true, export: true, dirty: true, save: true, events: true, marks: true,
               changes: true, locate: true, subgraphs: true, readGraph: true, applyOps: true, openWorkflow: true, toSubgraph: true,
               unpackSubgraph: true };
const LOADER = { id: "4", type: "CheckpointLoaderSimple", title: "Load Checkpoint",
                 widgets: [{ name: "ckpt_name", type: "combo", value: "sdxl.safetensors", combo: true }] };
const SAFE: ModelNsfw = { flagged: false, manual: null, reasons: [] };
const FLAGGED: ModelNsfw = { flagged: true, manual: true, reasons: [] };

function model(name: string, overrides: Partial<ModelFile> = {}): ModelFile {
  return {
    folder: "checkpoints", name, size: 6_900_000_000, modified: 1700000000, family: "SDXL", family_source: "metadata", triggers: [],
    triggers_source: "", title: "", has_preview: true, preview_origin: "server", preview_kind: "image", used_by: [], nsfw: SAFE, ...overrides,
  };
}

let log: string[];
function desktop() {
  log = [];
  const comfyWorkbench = vi.fn(async ({ call }: { call: ComfyWorkbenchCall }) => {
    if (call.op === "setWidget") return { ok: true, value: call.value };
    return { ok: true };
  });
  vi.stubGlobal("mosaelBrowser", {
    openComfyWorkbench: vi.fn(async () => ({ ok: true, outcome: "opened" })),
    comfyWorkbench,
    onComfyWorkbench: () => () => undefined,
  });
  const stand = () => (document.querySelector("[data-native-view-stand-in]") ? "on" : "off");
  const publish = {
    snapshotPage: vi.fn(async () => {
      log.push("snapshot");
      return { frame: "data:image/jpeg;base64,ZnJhbWU=", bounds: { x: 0, y: 56, width: 1020, height: 844 } };
    }),
    setOverlay: vi.fn(async (up: boolean) => {
      await new Promise((resolve) => setTimeout(resolve, 10));
      log.push(`${up ? "aside" : "back"}:frame=${stand()}`);
    }),
  };
  vi.stubGlobal("mosaelPublish", publish);
  return { comfyWorkbench, publish };
}

async function mount(node = LOADER, below: React.ReactNode = null) {
  const bridge = desktop();
  await openWorkbench(TARGET, { path: "人像/古风.json" });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
        {below}
        {/* 和工作台那一列一样:外壳(APP_CHROME),里面的东西在外壳的区域里(见 ComfyWorkbench 的 COLUMN_REGION) */}
        <aside {...APP_CHROME}>
          <HintRegion.Provider value={{ side: "left" }}>
            <ModelsPanel target={TARGET} node={node} capabilities={CAPS} />
          </HintRegion.Provider>
        </aside>
        <NativeViewStandIn />
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
  await screen.findByText("SDXL Base");
  return bridge;
}

const row = (title: string) => screen.getByText(title).closest<HTMLElement>("[data-model-row]")!;
const detailDialog = () => document.querySelector<HTMLElement>("[data-workbench-model-detail]");

/** 画面「加载好了」(jsdom 不解码图片)。 */
async function frameLoads() {
  const frame = await waitFor(() => {
    const found = document.querySelector<HTMLImageElement>("[data-native-view-stand-in]");
    expect(found).not.toBeNull();
    return found!;
  });
  fireEvent.load(frame);
}

beforeEach(() => {
  window.localStorage.clear();
  for (const fn of Object.values(api)) if (typeof fn === "function" && "mockReset" in fn) (fn as ReturnType<typeof vi.fn>).mockReset();
  api.getNodeFolders.mockResolvedValue({ folders: ["checkpoints"] });
  api.getLocalNsfw.mockResolvedValue({ status: "missing", message: "", size_bytes: 22404720, pending: 0, scored: 0 });
  api.listGenerationOptions.mockResolvedValue([]);
  api.getModelDetail.mockImplementation(async (_id: string, folder: string, name: string) => ({
    folder, name, metadata: { "modelspec.architecture": "stable-diffusion-xl-v1-base" }, tags: [],
  }));
  api.getModelLibrary.mockResolvedValue({
    folders: [{ name: "checkpoints", count: 3 }], missing: [], download: { route: "local", note: "" },
    preview_tools: { lookup: "sha256", save: true, save_note: "" },
    models: [
      model("sdxl.safetensors", { title: "SDXL Base", used_by: [{ id: "人像/古风.json", label: "古风" }] }),
      model("pony.safetensors", { title: "Pony", nsfw: FLAGGED }),
      model("flux-dev.safetensors", { title: "Flux Dev", family: "Flux", has_preview: false }),
    ],
  });
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

afterEach(() => {
  resetWorkbench();
  resetNativeViewAside();
  vi.unstubAllGlobals();
});

describe("工作台模型库里的模型详情", () => {
  it("每一行的「查看详情」打开那个模型的详情;画布先铺冻结的画面再让开,关上先放回再拿掉画面,焦点回到那一行", async () => {
    const bridge = await mount();
    const info = within(row("Pony")).getByRole("button", { name: "workbenchModelDetailOpen" });
    expect(info.className, "平时藏着,悬停、聚焦这一行时露出来").toMatch(/\bopacity-0\b/);
    expect(info.className).toMatch(/group-hover\/thumb:opacity-100/);
    expect(info.className).toMatch(/focus-visible:opacity-100/);
    info.focus();
    fireEvent.click(info);

    const dialog = await waitFor(() => {
      const found = detailDialog();
      expect(found).not.toBeNull();
      return found!;
    });
    expect(within(dialog).getByRole("heading", { name: "pony.safetensors" }), "模型库那一页详情:名字是文件名").toBeInTheDocument();
    expect(dialog.className, "压在外壳(z-200)之上").toMatch(/\bz-\[205\]/);
    //: 没有弹窗标题栏给详情的固定头垫上边距:弹窗自己出,和左右的 px-6 一样
    expect(dialog.className, "名字和按钮不贴着弹窗上沿").toMatch(/\bpt-6\b/);
    expect(document.querySelector(".modal-overlay")?.className).toMatch(/\bz-\[205\]/);
    //: 和模型库同一份本事:NSFW 那一行能改手动标记;同一份预览图设置:NSFW 默认模糊
    expect(within(dialog).getByText("modelNsfwRow")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /modelNsfwUnmark/ })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /modelRevealPreview/ }), "判成 NSFW 的预览图默认模糊,点了才看清").toBeInTheDocument();

    await frameLoads();
    await waitFor(() => expect(log).toEqual(["snapshot", "aside:frame=on"]));

    fireEvent.click(within(dialog).getByRole("button", { name: "workbenchModelDetailClose" }));
    await waitFor(() => expect(detailDialog()).toBeNull());
    await waitFor(() => expect(log).toEqual(["snapshot", "aside:frame=on", "back:frame=on"]));
    await waitFor(() => expect(document.querySelector("[data-native-view-stand-in]")).toBeNull());
    await waitFor(() => expect(document.activeElement, "焦点回到那一行的「查看详情」").toBe(info));
    expect(bridge.comfyWorkbench, "看详情不改画布").not.toHaveBeenCalled();
  });

  it("右键一行:模型库那一份菜单,第一项「查看详情」,选了打开那个模型的详情", async () => {
    await mount();
    fireEvent.contextMenu(row("Flux Dev"));
    const menu = await screen.findByRole("menu");
    const items = within(menu).getAllByRole("menuitem");
    expect(items[0].textContent).toContain("workbenchModelDetail");
    expect(within(menu).getByText("modelCopyName"), "别的照模型库那一份").toBeInTheDocument();
    fireEvent.click(items[0]);
    const dialog = await waitFor(() => {
      const found = detailDialog();
      expect(found).not.toBeNull();
      return found!;
    });
    expect(within(dialog).getByRole("heading", { name: "flux-dev.safetensors" })).toBeInTheDocument();
    expect(within(dialog).getByText("modelNoPreview"), "没有预览图的画占位").toBeInTheDocument();
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(detailDialog()).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(within(row("Flux Dev")).getByRole("button", { name: "workbenchModelDetailOpen" })));
  });

  it("底下还开着工作流库(工作台就是从它打开的):在详情里点、按 Esc 只关详情,工作流库还在", async () => {
    const guards = installAppChromeGuards(document);
    try {
      const libraryOpenChange = vi.fn();
      await mount(LOADER, <ModalShell open onOpenChange={libraryOpenChange} title="工作流库"><p>列表</p></ModalShell>);
      //: Radix 等 setTimeout(0) 之后才开始听「点了外面」
      await new Promise((resolve) => setTimeout(resolve, 10));
      const info = within(row("SDXL Base")).getByRole("button", { name: "workbenchModelDetailOpen" });
      fireEvent.pointerDown(info);
      fireEvent.click(info);
      const dialog = await waitFor(() => {
        const found = detailDialog();
        expect(found).not.toBeNull();
        return found!;
      });
      await new Promise((resolve) => setTimeout(resolve, 10));
      const copy = within(dialog).getByRole("button", { name: /modelCopyName/ });
      fireEvent.pointerDown(copy);
      fireEvent.click(copy);
      fireEvent.keyDown(dialog, { key: "Escape" });
      await waitFor(() => expect(detailDialog()).toBeNull());
      expect(libraryOpenChange, "工作流库没被这几下关掉").not.toHaveBeenCalled();
      expect(screen.getByRole("dialog", { name: "工作流库" })).toBeInTheDocument();
    } finally {
      guards();
    }
  });

  it("点一行本身照旧是填进画布,不开详情", async () => {
    const bridge = await mount();
    fireEvent.click(within(row("Flux Dev")).getByRole("button", { pressed: false, name: /Flux Dev/ }));
    await waitFor(() => expect(bridge.comfyWorkbench).toHaveBeenCalledWith({
      connectionId: "i1", call: { op: "setWidget", node: "4", widget: "ckpt_name", value: "flux-dev.safetensors" },
    }));
    expect(detailDialog()).toBeNull();
    expect(bridge.publish.setOverlay).not.toHaveBeenCalled();
  });

  it("详情里的预览图照模型库那两组设置:预览图不显示时只画占位,点「显示这一张」才去取", async () => {
    window.localStorage.setItem("mosael:model-previews", JSON.stringify({ level: "hidden", nsfw: "hidden" }));
    await mount();
    fireEvent.click(within(row("SDXL Base")).getByRole("button", { name: "workbenchModelDetailOpen" }));
    const dialog = await waitFor(() => {
      const found = detailDialog();
      expect(found).not.toBeNull();
      return found!;
    });
    expect(dialog.querySelector("[data-hidden-preview]")).not.toBeNull();
    expect(dialog.querySelector('img[src^="preview://"], img[src^="thumb://"]'), "不显示就不去取图").toBeNull();
    act(() => void fireEvent.click(within(dialog).getByRole("button", { name: /modelShowHiddenPreview/ })));
    expect(dialog.querySelector("[data-hidden-preview]")).toBeNull();
  });
});
