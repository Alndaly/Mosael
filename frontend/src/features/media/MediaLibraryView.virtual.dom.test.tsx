/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getAssetFacets, listAssetPage, type AssetCard, type AssetPage, type Workspace } from "@/api/client";
import { MediaLibraryView } from "./MediaLibraryView";

/**
 * 素材页只画看得见的那几行(网格和列表都是),滚到最后几行才取下一页;缩略图懒加载。
 * 此前一千多张卡片一次全挂在页面上(两万多个 DOM 节点),每张卡片还各带一套菜单、悬停说明。
 */

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  listAssetPage: vi.fn(),
  getAssetFacets: vi.fn(),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "en" }) }));
vi.mock("@/features/media/recordingContext", () => ({ useRecorder: () => ({ openRecorder: vi.fn() }) }));
vi.mock("@/features/media/UrlImportDialog", () => ({ UrlImportDialog: () => null }));
vi.mock("@/features/media/AssetPreviewModal", () => ({ AssetPreviewModal: () => null }));

const card = (id: string): AssetCard => ({
  id, name: id, workspace_id: "ws", project_id: null, original_filename: `${id}.png`, kind: "image", source: "imported", tags: [],
  derived: false, ai_generated: false, intermediate: "", created_at: "2026-01-01T00:00:00", updated_at: "2026-01-01T00:00:00",
  media_info: { duration: null, width: 100, height: 100, fps: null, has_thumbnail: true, format: null, pages: null, size_bytes: null },
});
const pageOf = (from: number, n: number, next: string | null, total: number): AssetPage => ({
  items: Array.from({ length: n }, (_, at) => card(`a${from + at}`)),
  next_cursor: next,
  total,
});

beforeEach(() => {
  localStorage.clear();
  window.location.hash = "#/media";
  vi.mocked(listAssetPage).mockReset();
  vi.mocked(getAssetFacets).mockResolvedValue({ total: 400, kinds: { image: 400 }, tags: {}, intermediates: {} });
});
afterEach(cleanup);

function renderLibrary(display: "grid" | "list" = "grid") {
  localStorage.setItem("mosael:tab:media-display", display);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MediaLibraryView workspace={{ id: "ws" } as Workspace} />
    </QueryClientProvider>,
  );
}

const cards = () => document.querySelectorAll("[data-media-scroll] article");

it.each(["grid", "list"] as const)("%s:只画看得见的那几行,其余的用留白占着位置", async (display) => {
  vi.mocked(listAssetPage).mockResolvedValue(pageOf(0, 200, null, 200));
  renderLibrary(display);
  await screen.findByRole("button", { name: "a0" });
  expect(cards().length).toBeGreaterThan(0);
  expect(cards().length).toBeLessThan(100);
  expect(screen.queryByRole("button", { name: "a199" })).toBeNull();
  //: 下面没画的那些占着高度:滚动条的长度说的还是整份清单。
  const spacer = document.querySelector<HTMLElement>("[data-media-rows] > [data-pad-bottom]");
  expect(Number.parseFloat(spacer?.style.height ?? "0")).toBeGreaterThan(0);
});

it("滚到最后几行才取下一页,带着上一页的游标", async () => {
  vi.mocked(listAssetPage).mockImplementation(async (_query, cursor) =>
    cursor === "c1" ? pageOf(60, 60, null, 120) : pageOf(0, 60, "c1", 120),
  );
  renderLibrary("list");
  await screen.findByRole("button", { name: "a0" });
  expect(listAssetPage).toHaveBeenCalledTimes(1);
  const scroller = document.querySelector<HTMLElement>("[data-media-scroll]")!;
  const rows = document.querySelector<HTMLElement>("[data-media-rows]")!;
  //: jsdom 不排版:照真浏览器的样子,往下滚多少,清单的顶边就往上移多少。
  Object.defineProperty(scroller, "clientHeight", { configurable: true, value: 900 });
  rows.getBoundingClientRect = () => ({ top: -scroller.scrollTop, bottom: 0, left: 0, right: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}) });
  scroller.scrollTop = 60 * 113;
  await act(async () => {
    fireEvent.scroll(scroller);
    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
  });
  await waitFor(() => expect(vi.mocked(listAssetPage).mock.calls.at(-1)?.[1]).toBe("c1"));
});

it("缩略图懒加载、异步解码", async () => {
  vi.mocked(listAssetPage).mockResolvedValue(pageOf(0, 10, null, 10));
  renderLibrary("grid");
  await screen.findByRole("button", { name: "a0" });
  const thumbnail = document.querySelector<HTMLImageElement>("[data-media-scroll] article img")!;
  expect(thumbnail.getAttribute("loading")).toBe("lazy");
  expect(thumbnail.getAttribute("decoding")).toBe("async");
});
