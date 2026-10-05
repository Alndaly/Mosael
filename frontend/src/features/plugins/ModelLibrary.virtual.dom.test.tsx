/** @vitest-environment jsdom */

/**
 * 模型库只画看得见的那几行(网格和列表都是),滚到哪儿画到哪儿;从详情回来,刚才那一条(哪怕在几百个之后)画出来、
 * 焦点回到它身上。此前五百多个文件一次全挂在页面上:六千多个节点,一屏几十张原图,换目录、悬停、滚动都卡。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getModelLibrary: vi.fn(),
  getModelDetail: vi.fn(),
  getJob: vi.fn(),
  cancelJob: vi.fn(),
  resolveModelLink: vi.fn(),
  startModelDownload: vi.fn(),
  listGenerationOptions: vi.fn(async () => []),
  modelPreviewUrl: (instance: string, folder: string, name: string) => `preview://${instance}/${folder}/${name}`,
  modelThumbnailUrl: (instance: string, folder: string, name: string) => `thumbnail://${instance}/${folder}/${name}`,
}));
vi.mock("@/api/client", () => api);
vi.mock("@/api/domains/generation", () => ({ listGenerationOptions: api.listGenerationOptions }));
//: 大图走应用共用的灯箱(App 根上的 Provider);这里只看有没有交给它
const imagePreview = vi.hoisted(() => vi.fn());
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: imagePreview, isImagePreviewOpen: false }) }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh" }) }));
//: 数缩略图画了几次:卡片记忆化之后,弹窗为别的事重渲时它们不该跟着重画。
const thumbRenders = vi.hoisted(() => ({ count: 0 }));
vi.mock("@/components/generation/ModelThumb", async (original) => {
  const actual = await original<typeof import("@/components/generation/ModelThumb")>();
  return {
    ...actual,
    ModelThumb: (props: Parameters<typeof actual.ModelThumb>[0]) => {
      thumbRenders.count += 1;
      return actual.ModelThumb(props);
    },
  };
});

import type { ModelFile, ModelLibrary, PluginInstance } from "@/api/client";
import { ModelLibraryDialog } from "./ModelLibrary";

const instance = { id: "i1", name: "ComfyUI", blocked_reason: "" } as PluginInstance;
const COUNT = 500;
const name = (index: number) => `lora-${String(index).padStart(3, "0")}.safetensors`;

function library(): ModelLibrary {
  const models: ModelFile[] = Array.from({ length: COUNT }, (_, index) => ({
    folder: "loras", name: name(index), size: 1000 + index, modified: 1700000000 + index, family: "", family_source: "",
    triggers: [], triggers_source: "", title: "", has_preview: true, preview_origin: "", preview_kind: "image", used_by: [],
  }));
  return { folders: [{ name: "loras", count: COUNT }], models, missing: [], download: { route: "none", note: "" }, downloads: [] };
}

//: jsdom 不排版。照真浏览器给几个尺寸:网格 880 宽(小卡片一行 6 张)、内容区 900 高;往下滚多少,网格 / 表格的
//: 顶边就往上移多少。挂在原型上 —— 从详情回来时内容区是新挂上的那一个。
const scroller = () => document.querySelector<HTMLElement>("[data-library-content]")!;
const saved = {
  clientWidth: Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth")!,
  clientHeight: Object.getOwnPropertyDescriptor(Element.prototype, "clientHeight")!,
};

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView = () => {};
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get(this: HTMLElement) {
      return this.hasAttribute("data-model-grid") ? 880 : saved.clientWidth.get!.call(this);
    },
  });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", {
    configurable: true,
    get(this: HTMLElement) {
      return this.hasAttribute("data-library-content") ? 900 : saved.clientHeight.get!.call(this);
    },
  });
  Object.defineProperty(HTMLElement.prototype, "getBoundingClientRect", { configurable: true, writable: true, value: function (this: HTMLElement) {
    const content = this.closest<HTMLElement>("[data-library-content]");
    const top = content && this !== content && (this.matches("[data-model-grid], tbody")) ? -content.scrollTop : 0;
    return { top, bottom: top, left: 0, right: 0, width: 0, height: 0, x: 0, y: top, toJSON: () => ({}) } as DOMRect;
  } });
  api.getModelLibrary.mockReset();
  api.getModelLibrary.mockResolvedValue(library());
  api.getModelDetail.mockReset();
  api.getModelDetail.mockImplementation(async (_id: string, folder: string, file: string) => ({ folder, name: file, metadata: {}, tags: [] }));
});

afterEach(() => {
  cleanup();
  for (const key of ["clientWidth", "clientHeight", "getBoundingClientRect"]) Reflect.deleteProperty(HTMLElement.prototype, key);
});

function open() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ModelLibraryDialog open onOpenChange={() => {}} instance={instance} workspaceId="w1" />
    </QueryClientProvider>,
  );
}

const items = () => Array.from(document.querySelectorAll<HTMLElement>("[data-library-item]")).map((one) => one.dataset.libraryItem);

async function scrollTo(top: number) {
  scroller().scrollTop = top;
  await act(async () => {
    fireEvent.scroll(scroller());
    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
  });
}

it("网格:五百个文件只画看得见的那几行,其余的用留白占着高度;滚到哪儿画到哪儿", async () => {
  open();
  const list = await screen.findByRole("list", { name: "modelLibraryTitle" });
  const mounted = items();
  expect(mounted.length).toBeGreaterThan(0);
  expect(mounted.length).toBeLessThan(80);
  expect(mounted.length % 6).toBe(0);
  expect(mounted[0]).toBe(`loras/${name(0)}`);
  expect(document.querySelectorAll("[data-library-content] img").length).toBe(mounted.length);
  //: 没画的那些占着高度:滚动条说的还是整份清单;读屏也知道一共几个、这是第几个。
  expect(Number.parseFloat(list.querySelector<HTMLElement>(":scope > [data-pad-bottom]")!.style.height)).toBeGreaterThan(10000);
  const first = within(list).getAllByRole("listitem")[0];
  expect(first.getAttribute("aria-setsize")).toBe(String(COUNT));
  expect(first.getAttribute("aria-posinset")).toBe("1");

  await scrollTo(60 * 255);
  const later = items();
  expect(later).toContain(`loras/${name(360)}`);
  expect(later).not.toContain(`loras/${name(0)}`);
  expect(later.length).toBeLessThan(80);
  expect(Number.parseFloat(list.querySelector<HTMLElement>(":scope > [data-pad-top]")!.style.height)).toBeGreaterThan(5000);
});

it("列表:一样只画看得见的那几行,表头之外上下各一个空行撑着高度", async () => {
  localStorage.setItem("mosael:tab:model-library.density", "list");
  open();
  const table = await screen.findByRole("table", { name: "modelLibraryTitle" });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows.length).toBeGreaterThan(10);
  expect(rows.length).toBeLessThan(100);
  await scrollTo(300 * 49);
  expect(items()).toContain(`loras/${name(300)}`);
  expect(items()).not.toContain(`loras/${name(0)}`);
});

it("从详情回来:滚回原处,刚才点开的那一张(几百个之后)画出来、焦点回到它身上", async () => {
  open();
  await screen.findByRole("list", { name: "modelLibraryTitle" });
  await scrollTo(60 * 255);
  const target = `loras/${name(363)}`;
  const card = document.querySelector<HTMLElement>(`[data-library-item="${target}"]`)!;
  fireEvent.click(within(card).getByRole("button", { name: name(363) }));
  fireEvent.click(await screen.findByRole("button", { name: "modelLibraryBack" }));
  await screen.findByRole("list", { name: "modelLibraryTitle" });
  expect(scroller().scrollTop).toBe(60 * 255);
  const back = document.querySelector<HTMLElement>(`[data-library-item="${target}"]`);
  expect(back).toBeTruthy();
  expect(document.activeElement).toBe(back!.querySelector("[data-library-open]"));
});

it("弹窗为别的事重渲(比如搜索框里打字)时,已经画着的卡不跟着重画;改了预览图那一档才重画", async () => {
  open();
  const list = await screen.findByRole("list", { name: "modelLibraryTitle" });
  const mounted = within(list).getAllByRole("listitem").length;
  const before = thumbRenders.count;
  //: 五百个都叫 lora-…:筛完还是同一批文件,卡片拿到的东西一样都没变。
  fireEvent.change(screen.getByRole("textbox", { name: "modelLibrarySearch" }), { target: { value: "lora" } });
  expect(within(list).getAllByRole("listitem")).toHaveLength(mounted);
  expect(thumbRenders.count).toBe(before);
  fireEvent.click(screen.getByRole("button", { name: "modelPreviewSettings" }));
  fireEvent.click(within(screen.getByRole("radiogroup", { name: "modelPreviewLevel" })).getByRole("radio", { name: "modelPreviewLevelLight" }));
  expect(thumbRenders.count).toBe(before + mounted);
});
