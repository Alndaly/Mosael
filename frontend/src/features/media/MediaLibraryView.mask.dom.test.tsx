/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";

/**
 * 素材库里的「生成蒙版」(ADR 0056 决定 6):对**已有的一张图**算一张蒙版、落成一份新素材。
 *
 * 钉住的是这条路本身:入口在素材动作里(只有图片有)、参数就是后端那只 request 的五个字段、提交打到
 * `POST /api/assets/{id}/mask` 上、成了说一声并**把新素材开出来**;不成照实说后端那一句,不假装成功。
 *
 * 形状那四步(阈值 → 反选 → 扩张 → 羽化)是后端的事,这里只证明界面把选中的值原样发过去了 ——
 * mock 的只有素材列表那两条和 fetch,`makeAssetMask` 走的是真的那一个(路径、方法、body 都看得见)。
 */

const TEXT: Record<string, string> = { assetMaskDone: "已生成「{name}」" };
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => TEXT[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

const toasts = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), message: vi.fn(), info: vi.fn() }));
vi.mock("sonner", () => ({ toast: toasts }));

const opened = vi.hoisted(() => [] as string[]);
vi.mock("@/features/media/AssetPreviewModalById", () => ({
  AssetPreviewModalById: ({ id }: { id: string | null }) => {
    if (id) opened.push(id);
    return null;
  },
}));
//: 这两样这里都不测:看大图是 image-preview 自己的事,导入地址栏另有一组测试。
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn(), isImagePreviewOpen: false }) }));
vi.mock("@/features/media/UrlImportDialog", () => ({ UrlImportDialog: () => null }));
vi.mock("@/features/media/recordingContext", () => ({ useRecorder: () => ({ openRecorder: vi.fn() }) }));

import { getAssetFacets, listAssetPage, type AssetCard, type Workspace } from "@/api/client";
import { MediaLibraryView } from "./MediaLibraryView";

//: 素材列表照旧给桩(那是素材库自己的事);`makeAssetMask` **不给** —— 它走真的那一个,落到下面的 fetch 上。
vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  listAssetPage: vi.fn(),
  getAssetFacets: vi.fn(async () => ({ total: 0, kinds: {}, tags: {}, intermediates: {} })),
}));

const card = (id: string, kind: string): AssetCard => ({
  id, name: id, workspace_id: "ws", project_id: null, original_filename: id, kind, source: "imported", tags: [],
  derived: false, ai_generated: false, intermediate: "",
  media_info: { duration: null, width: null, height: null, fps: null, has_thumbnail: false, format: null, pages: null, size_bytes: null },
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

/** 这一次 POST /mask 后端回什么(默认:成了)。 */
const reply = { current: () => json({ id: "mask-1", name: "蒙版 · still" }) };
const posts: Array<{ url: string; method: string; body: Record<string, unknown> }> = [];

const originalFetch = globalThis.fetch;
//: radix 的滑杆挂载时要量一次尺寸(`@radix-ui/react-use-size`),jsdom 没有 ResizeObserver。
beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});
beforeEach(() => {
  posts.length = 0;
  opened.length = 0;
  toasts.success.mockReset();
  toasts.error.mockReset();
  reply.current = () => json({ id: "mask-1", name: "蒙版 · still" });
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST") {
      posts.push({ url, method: init.method, body: JSON.parse(String(init.body)) });
      return reply.current();
    }
    return json([]);
  }) as never;
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  cleanup();
});

function mount(cards: AssetCard[]) {
  localStorage.clear();
  vi.mocked(listAssetPage).mockImplementation(async () => ({ items: cards, next_cursor: null, total: cards.length }));
  vi.mocked(getAssetFacets).mockResolvedValue({
    total: cards.length,
    kinds: { image: cards.filter((one) => one.kind === "image").length },
    tags: {},
    intermediates: {},
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  render(<QueryClientProvider client={client}><MediaLibraryView workspace={{ id: "ws", role: "editor" } as Workspace} /></QueryClientProvider>);
}

/** ⋯ 菜单 → 「生成蒙版…」,把那张对话框拿回来。 */
async function openMaskDialog(id: string) {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: `studioActions: ${id}` }));
  await user.click(await screen.findByRole("menuitem", { name: "assetMakeMask" }));
  return { user, dialog: await screen.findByRole("dialog", { name: "assetMaskTitle" }) };
}

it("改几个参数提交:打到 POST /api/assets/{id}/mask 上,发的是那几个字段;成了说一声并打开新素材", async () => {
  mount([card("still", "image"), card("clip", "video")]);
  const { user, dialog } = await openMaskDialog("still");

  // 来源:按亮度 → 按 alpha。
  await user.click(within(dialog).getByRole("radio", { name: "assetMaskSourceAlpha" }));
  // 阈值:滑杆拨一格(0.5 → 0.51)。
  const slider = within(dialog).getByRole("slider");
  slider.focus();
  fireEvent.keyDown(slider, { key: "ArrowRight", code: "ArrowRight" });
  // 反选、扩张、羽化各改一格。
  await user.click(within(dialog).getByRole("switch"));
  const grow = within(dialog).getByRole("spinbutton", { name: "assetMaskGrow" });
  await user.clear(grow);
  await user.type(grow, "8");
  const feather = within(dialog).getByRole("spinbutton", { name: "maskFeatherRadius" });
  await user.clear(feather);
  await user.type(feather, "4");

  await user.click(within(dialog).getByRole("button", { name: "assetMaskStart" }));

  await waitFor(() => expect(posts.filter((one) => one.url.includes("/mask"))).toHaveLength(1));
  const posted = posts.find((one) => one.url.includes("/mask"))!;
  expect(posted.url).toContain("/api/assets/still/mask");
  expect(posted.method).toBe("POST");
  //: 五个字段就是后端那只 request 的五个:形状那四步的先后由后端定,界面只把选中的值原样发过去。
  expect(posted.body).toEqual({ source: "alpha", threshold: 0.51, invert: true, grow: 8, feather: 4 });

  //: 成了:说一声(名字是后端给的那个),并把新素材开出来。
  await waitFor(() => expect(toasts.success).toHaveBeenCalledWith("已生成「蒙版 · still」"));
  await waitFor(() => expect(opened).toContain("mask-1"));
  expect(toasts.error).not.toHaveBeenCalled();
});

it("只给图片这一步:视频的菜单里没有这一条", async () => {
  mount([card("clip", "video")]);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "studioActions: clip" }));
  await screen.findByRole("menuitem", { name: "rename" });
  expect(screen.queryByRole("menuitem", { name: "assetMakeMask" })).not.toBeInTheDocument();
});

it("后端 400 说算不出这张蒙版:照实说那一句,不假装成功", async () => {
  mount([card("still", "image")]);
  reply.current = () => json({ detail: "这不是一张图片，算不出蒙版。" }, 400);
  const { user, dialog } = await openMaskDialog("still");

  await user.click(within(dialog).getByRole("button", { name: "assetMaskStart" }));

  await waitFor(() => expect(toasts.error).toHaveBeenCalledWith("这不是一张图片，算不出蒙版。"));
  expect(toasts.success).not.toHaveBeenCalled();
  expect(opened).toEqual([]);
  //: 参数还能改,所以弹窗留着 —— 不关掉、也不当作成了。
  expect(screen.getByRole("dialog", { name: "assetMaskTitle" })).toBeInTheDocument();
});
