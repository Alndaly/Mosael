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
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
import { NativeViewStandIn, resetNativeViewAside, settleNativeViewAside } from "@/components/ui/nativeViewAside";
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
    setHostLayer: vi.fn(async (claim: { kind: string; active: boolean }) => {
      if (claim.kind !== "overlay") return;
      await new Promise((resolve) => setTimeout(resolve, 10));
      log.push(`${claim.active ? "aside" : "back"}:frame=${stand()}`);
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
  api.getModelLibrary.mockImplementation(LIBRARY);
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

afterEach(async () => {
  // 先卸载、等「让开 / 放回」那一串走完,再重置:关上详情时那一串还在路上,不等就重置,它走完时把「拍画面 / 挪开」记进下一条测试
  // (打乱顺序、机器忙时实测:下一条的日志多出两笔)。
  cleanup();
  await settleNativeViewAside();
  resetWorkbench();
  resetNativeViewAside();
  vi.unstubAllGlobals();
});

/** 默认模型库(beforeEach 用);个别用例再追加模型时整体重设。 */
const LIBRARY = () => ({
  folders: [{ name: "checkpoints", count: 3 }], missing: [], download: { route: "local", note: "" },
  preview_tools: { lookup: "sha256", save: true, save_note: "" },
  models: [
    model("sdxl.safetensors", { title: "SDXL Base", used_by: [{ id: "人像/古风.json", label: "古风" }] }),
    model("pony.safetensors", { title: "Pony", nsfw: FLAGGED }),
    model("flux-dev.safetensors", { title: "Flux Dev", family: "Flux", has_preview: false }),
  ],
});

describe("工作台模型库里的模型详情", () => {
  it("每一行的「查看详情」打开那个模型的详情;画布先铺冻结的画面再让开,关上先放回再拿掉画面,焦点回到那一行", async () => {
    const bridge = await mount();
    const info = within(row("Pony")).getByRole("button", { name: "workbenchModelDetailOpen" });
    expect(info.className, "卡片形态下常显,不再靠悬停才出现").not.toMatch(/\bopacity-0\b/);
    expect(info.className).not.toMatch(/group-hover\/thumb:opacity-100/);
    expect(info.className, "压在图上,给了一层底才看得清").toMatch(/bg-background\/60/);
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
      //: 详情的内容是另拉的(模型详情接口):等它画出来再点。此前同步取,机器一忙就「找不到复制名字」。
      const copy = await within(dialog).findByRole("button", { name: /modelCopyName/ });
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
    expect(bridge.publish.setHostLayer.mock.calls.filter(([claim]) => claim.kind === "overlay")).toEqual([]);
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

/**
 * 模型行的徽标布局(维护者:「希望这些 badge 垂直高度是一致的」「NSFW 标应该在这些 badges 的最后」):
 * 名字独占第一行;第二行(meta)从左到右是 [底模徽标] [EncoderRecipeMark] [副题] [NSFW] [PreviewOriginMark]。
 * NSFW 与预览来源是一对、一起排在最后;所有徽标同一档高度(和 CatalogBadge 一样)。
 */
describe("模型行徽标布局:徽标同高、角标排最后", () => {
  it("① 两枚徽标同一档高度:NSFW 与底模徽标(CatalogBadge)最终都是 h-6", async () => {
    await mount();
    const mark = row("Pony").querySelector("[data-nsfw-mark]");
    expect(mark, "Pony 判成 NSFW:行里有这枚徽标").not.toBeNull();
    const meta = mark!.parentElement!;
    const family = within(meta).getByText("SDXL");
    const heights = (el: Element) => el.className.split(/\s+/).filter((one) => /^-?h-\d+(\.\d+)?$/.test(one));
    expect(heights(mark!), "NSFW 粉胶囊的高度类").toEqual(["h-6"]);
    expect(heights(family), "底模徽标(CatalogBadge)的高度类").toEqual(["h-6"]);
    expect(heights(mark!), "两枚徽标同一档尺码,不是两套").toEqual(heights(family));
  });

  it("② meta 行顺序:底模徽标 → 副题 → NSFW → PreviewOriginMark,角标在最后且成对", async () => {
    api.getModelLibrary.mockImplementation(() => Promise.resolve({
      ...LIBRARY(),
      models: [...LIBRARY().models, model("civ-dl.safetensors", { title: "Civ DL", nsfw: FLAGGED, preview_origin: "civitai" })],
    }));
    await mount();
    const rowEl = row("Civ DL");
    const mark = rowEl.querySelector("[data-nsfw-mark]");
    const origin = rowEl.querySelector("[data-preview-origin]");
    expect(mark, "判成 NSFW:行里有这枚徽标").not.toBeNull();
    expect(origin, "预览图来自 Civitai:行里有来源徽标").not.toBeNull();
    expect(origin!.parentElement, "两枚徽标同一个父元素、同一行(meta 行)").toBe(mark!.parentElement);
    const meta = origin!.parentElement!;
    expect(meta.className, "那一行是横排的 meta 行(items-center),不是行尾那列").toMatch(/\bitems-center\b/);
    const family = within(meta).getByText("SDXL");
    const subtitle = within(meta).getByText("civ-dl.safetensors");
    const order = [...meta.children];
    expect(order.indexOf(family), "底模徽标排在 NSFW 之前").toBeLessThan(order.indexOf(mark!));
    expect(order.indexOf(subtitle), "副题也在 NSFW 之前").toBeLessThan(order.indexOf(mark!));
    expect(order.indexOf(mark!), "NSFW 排在底模徽标之后").toBeGreaterThan(order.indexOf(family));
    expect(order.slice(-2), "NSFW 与预览来源是最后两枚、并排成对,不拆散").toEqual([mark, origin]);
  });

  it("③ 没有 hint(底模/家族/副题)只有 NSFW 的模型也显示徽标", async () => {
    api.getModelLibrary.mockImplementation(() => Promise.resolve({
      ...LIBRARY(),
      models: [...LIBRARY().models, model("raw-nsfw.safetensors", { title: "", family: "", nsfw: FLAGGED })],
    }));
    await mount();
    const mark = row("raw-nsfw.safetensors").querySelector("[data-nsfw-mark]");
    expect(mark, "meta 行的渲染条件要算上 NSFW,不然这种行不画徽标").not.toBeNull();
    expect(mark!.parentElement!.className, "画在横排的 meta 行里(items-center),不是行尾那列").toMatch(/\bitems-center\b/);
  });

  it("④ 名字仍在独立第一行:grid 两行结构,meta 是第二行", async () => {
    await mount();
    const nameEl = within(row("Pony")).getByText("Pony");
    const grid = nameEl.parentElement!;
    expect(grid.className, "名字和 meta 共用一个 grid 容器").toMatch(/\bgrid\b/);
    expect(grid.children[0], "名字独占第一行").toBe(nameEl);
    const meta = grid.children[1];
    expect(meta, "有第二行").not.toBeUndefined();
    expect(meta.className).toMatch(/\bflex\b/);
    expect(meta.querySelector("[data-nsfw-mark]"), "第二行就是 meta 行,徽标挪进来了").not.toBeNull();
  });

  it("⑤ 行尾独立的徽标列不存在了(源码里没有那个 flex-col items-end 块)", async () => {
    const fs = await import("node:fs");
    const source = fs.readFileSync("./src/features/plugins/workbench/ModelsPanel.tsx", "utf8");
    expect(source, "右侧独立徽标列已删").not.toContain("flex-col items-end");
  });

  it("⑥ 模型列表是响应式多列网格:auto-fill + minmax 按容器宽度自己变列数,不是一行一条", async () => {
    await mount();
    const list = screen.getByRole("list", { name: "workbenchModelsList" });
    expect(list.className, "列数靠容器宽度自己变(auto-fill),不写死断点").toMatch(
      /grid-cols-\[repeat\(auto-fill,minmax\(10rem,1fr\)\)\]/,
    );
    expect(list.className, "是 grid,不是 flex 行").toMatch(/\bgrid\b/);
    expect(list.className).not.toMatch(/\bflex\b/);
    expect(list.className, "卡片之间留出呼吸的间距").toMatch(/\bgap-3\b/);
  });

  it("⑪ 搜索框和右边那颗小眼睛同高 —— 两边都按 xs 档(28)", async () => {
    // 维护者:「这个 input 框的高度和右侧的那个眼睛按钮的高度不一致」✗。
    // 同高不能靠两处碰巧写了同一个数(见 components/ui/control-size.ts 开头那段),所以两处都从刻度取:
    // 搜索框走 SEARCH_FIELD/Field 的 xs(h-7),小眼睛走 CONTROL_SQUARE.xs(size-7),都是 28。
    await mount();
    const field = document.querySelector("[data-search-input]");
    expect(field, "面板上有搜索框").not.toBeNull();
    const parts = [field as Element, ...Array.from(field!.querySelectorAll("*"))];
    expect(parts.some((el) => /\bh-7\b/.test((el as HTMLElement).className || "")), "搜索框按 xs 档 28").toBe(true);
    const eye = screen.getByRole("button", { name: "modelPreviewSettings" });
    expect(eye.className, "小眼睛也按 xs 档 28,不与搜索框差一截").toMatch(/\bsize-7\b/);
  });

  it("⑫ 卡片框常显:没选中、没悬停时也有实边框和卡片底色", async () => {
    // 维护者:「卡片框没选中 / hover 的情况下也得有,否则看上去就像多了莫名其妙的间距」✗。
    // 透明描边 + 透明底 = 每张卡只剩内容浮在面板底色上,卡与卡之间那条缝看起来像多出来的间距。
    await mount();
    const card = row("Pony"); // 未选中那张（SDXL Base 是已选中的,选中态本来就该是 primary 描边）
    expect(card.className, "未选中也有实边框").toMatch(/\bborder-border\b/);
    expect(card.className, "不再是透明描边").not.toMatch(/\bborder-transparent\b/);
    expect(card.className, "有卡片底色").toMatch(/\bbg-card\b/);
    expect(card.className, "圆角把封面裁进卡里").toMatch(/\boverflow-hidden\b/);
    expect(card.className).toMatch(/\brounded-lg\b/);
  });

  it("⑦ 缩略图固定 4:3、填满卡片宽度,图片 object-cover:图片不撑高卡片,卡是竖排(图在上、字在下)", async () => {
    await mount();
    const card = row("SDXL Base");
    const img = card.querySelector<HTMLImageElement>("img");
    expect(img, "有预览图的卡里有图").not.toBeNull();
    expect(img!.className, "裁切填满,不按原图比例撑开").toMatch(/\bobject-cover\b/);
    const box = img!.parentElement!.closest<HTMLElement>("[class*='h-24']");
    expect(box, "固定高度写在缩略图那一层").not.toBeNull();
    expect(box!.className, "封面固定高度,不按原图或面板宽度变").toMatch(/\bh-24\b/);
    expect(box!.className, "填满卡片宽度").toMatch(/\bw-full\b/);
    expect(box!.closest("[data-model-row]"), "缩略图在卡里").toBe(card);
    const pick = within(card).getByRole("button", { pressed: true });
    expect(pick.className, "卡是竖排 grid:缩略图一格、名字与 meta 一格").toMatch(/\bgrid\b/);
    expect(pick.children[0], "缩略图是第一格").toBe(box);
  });

  it("⑧ 卡内角标:ⓘ 压在缩略图右上、✓/转圈压在右下;一上一下对角、永不重叠,✓ 不挡点击", async () => {
    await mount();
    const card = row("SDXL Base");
    const info = within(card).getByRole("button", { name: "workbenchModelDetailOpen" });
    const state = card.querySelector<HTMLElement>("[data-model-state]");
    const box = card.querySelector<HTMLElement>("[class*='h-24']")!;
    const pick = within(card).getByRole("button", { pressed: true });

    //: 封面图到边(卡片不再留白,维护者:「封面和卡片之间不需要内间距」),所以 ⓘ 直接在图的角上内收 6px
    expect(card.className, "<li> 是定位上下文").toMatch(/\brelative\b/);
    expect(pick.className, "卡片不再留白,图到边").toMatch(/\bp-0\b/);
    expect(info.className, "绝对定位,不再占一格").toMatch(/\babsolute\b/);
    expect(info.className, "缩略图右上角").toMatch(/\bright-1\.5\b/);
    expect(info.className).toMatch(/\btop-1\.5\b/);
    expect(info.className, "ⓘ 不在下沿").not.toMatch(/\bbottom-/);
    expect(info.className, "层叠在缩略图之上").toMatch(/\bz-10\b/);
    expect(info.className, "常显:不再有藏/现两态").not.toMatch(/\bopacity-0\b/);
    expect(info.className).not.toMatch(/group-hover\/thumb:opacity-100/);
    expect(info.className).not.toMatch(/group-focus-within\/thumb:opacity-100/);
    expect(info.className, "压在图上要有底").toMatch(/bg-background\/60/);

    //: ✓ / 转圈在缩略图右下角,和右上角的 ⓘ 分处两头(不共用任何一条横边)
    expect(state, "已选中:卡里有 ✓ 这一层").not.toBeNull();
    expect(box.contains(state!), "✓ 画在缩略图那一层").toBe(true);
    expect(state!.className, "脱离文档流").toMatch(/\babsolute\b/);
    expect(state!.className, "缩略图右下角").toMatch(/\bright-1\.5\b/);
    expect(state!.className).toMatch(/\bbottom-1\.5\b/);
    expect(state!.className, "和 ⓘ 的 top 分处上下").not.toMatch(/\btop-/);
    expect(state!.className, "两个角标都在内容之上").toMatch(/\bz-10\b/);
    expect(state!.className, "不许挡缩略图的点击").toMatch(/\bpointer-events-none\b/);
    expect(state!.getAttribute("aria-hidden"), "只是画给人看的状态,读屏听 aria-pressed/aria-busy").not.toBeNull();
    expect(pick.querySelector("[data-model-state]"), "状态跟着填画布那张卡按钮(pending 时转圈的那一处)").toBe(state);
    expect(row("Flux Dev").querySelector("[data-model-state]"), "未选中不显示").toBeNull();
  });

  it("⑨ 键盘可达:每张卡是一颗可聚焦的按钮,ⓘ、缩略图预览层是另两颗;四个 data-model-* 都在", async () => {
    const bridge = await mount();
    const card = row("Pony");
    const pick = within(card).getByRole("button", { pressed: false });
    expect(pick.tagName).toBe("BUTTON");
    pick.focus();
    expect(document.activeElement, "卡片本身能聚焦").toBe(pick);

    const info = within(card).getByRole("button", { name: "workbenchModelDetailOpen" });
    info.focus();
    expect(document.activeElement, "ⓘ 是独立可聚焦的按钮").toBe(info);

    const preview = within(card).getByRole("button", { name: "workbenchModelsPreview" });
    preview.focus();
    expect(document.activeElement, "看大图那层也是按钮").toBe(preview);
    fireEvent.click(preview);
    expect(bridge.comfyWorkbench, "点缩略图是看大图,不是填画布").not.toHaveBeenCalled();

    expect(card.hasAttribute("data-model-row")).toBe(true);
    expect(card.querySelector("[data-model-detail]")).toBe(info);
    expect(card.querySelector("[data-model-preview]")).toBe(preview);
    expect(row("SDXL Base").querySelector("[data-model-state]"), "选中的那张卡有 ✓").not.toBeNull();
  });

  it("⑩ 名字与副题的 Truncate 都显式 side=\"bottom\":不跟着工作台那一列默认的「朝左」横到画布上", async () => {
    const fs = await import("node:fs");
    const source = fs.readFileSync("./src/features/plugins/workbench/ModelsPanel.tsx", "utf8");
    expect(source, "名字的 Truncate 显式朝下(工作台那一列是 side: left,不显式给就横在卡的左边)").toMatch(
      /<Truncate\b[^>]*\bside="bottom"[^>]*>\{name\}<\/Truncate>/,
    );
    expect(source, "副题也一样:卡片更窄,说明更该往下弹").toMatch(
      /<Truncate\b[^>]*\bside="bottom"[^>]*>\{subtitle\}<\/Truncate>/,
    );
  });
});
