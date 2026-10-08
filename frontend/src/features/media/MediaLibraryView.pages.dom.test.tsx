/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
//: 这里不测看大图(那是 image-preview 自己和各处接线测试的事),只给一个桩让组件挂得上。
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn(), isImagePreviewOpen: false }) }));
import { getAsset, getAssetFacets, listAssetPage, type AssetCard, type AssetPage, type Workspace } from "@/api/client";
import { MediaLibraryView } from "./MediaLibraryView";

/**
 * 素材页按页取:首屏只要第一页、筛选和搜索交给服务端、滚到底下才取下一页、页签上的数字另取。
 * 此前一次拉回整个工作区(一千多份素材、将近 1 MB),再在浏览器里筛、排、数,打开要好几秒。
 */

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  listAssetPage: vi.fn(),
  getAssetFacets: vi.fn(),
  getAsset: vi.fn(),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => (key === "mediaSelectedCount" ? "selected {n}" : key),
  usePreferences: () => ({ locale: "en" }),
}));
vi.mock("@/features/media/recordingContext", () => ({ useRecorder: () => ({ openRecorder: vi.fn() }) }));
vi.mock("@/features/media/UrlImportDialog", () => ({ UrlImportDialog: () => null }));
vi.mock("@/features/media/AssetPreviewModal", () => ({
  AssetPreviewModal: ({ asset }: { asset: { id: string } | null }) => (asset ? <div data-testid="preview">{asset.id}</div> : null),
}));

const card = (id: string, kind = "image"): AssetCard => ({
  id, name: id, workspace_id: "ws", project_id: null, original_filename: `${id}.png`, kind, source: "imported", tags: [],
  derived: false, ai_generated: false, intermediate: "", created_at: "2026-01-01T00:00:00", updated_at: "2026-01-01T00:00:00",
  media_info: { duration: null, width: 100, height: 100, fps: null, has_thumbnail: false, format: null, pages: null, size_bytes: null },
});

/** 一页 n 张卡片,id 从 from 起编号。 */
const pageOf = (from: number, n: number, next: string | null, total: number): AssetPage => ({
  items: Array.from({ length: n }, (_, at) => card(`a${from + at}`)),
  next_cursor: next,
  total,
});

beforeEach(() => {
  localStorage.clear();
  window.location.hash = "#/media";
  vi.mocked(listAssetPage).mockReset();
  vi.mocked(getAssetFacets).mockReset();
  vi.mocked(getAssetFacets).mockResolvedValue({ total: 130, kinds: { video: 30, image: 100 }, tags: { 海边: 4 }, intermediates: {} });
});
afterEach(cleanup);

function renderLibrary() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MediaLibraryView workspace={{ id: "ws" } as Workspace} />
    </QueryClientProvider>,
  );
}

it("首屏只取第一页,页签上的数字来自另取的计数", async () => {
  vi.mocked(listAssetPage).mockResolvedValue(pageOf(0, 60, "c1", 130));
  renderLibrary();
  expect(await screen.findByRole("button", { name: "a0" })).toBeInTheDocument();
  expect(listAssetPage).toHaveBeenCalledTimes(1);
  expect(vi.mocked(listAssetPage).mock.calls[0][0]).toMatchObject({ workspace_id: "ws", sort: "created" });
  expect(vi.mocked(listAssetPage).mock.calls[0][1]).toBeNull();
  expect(screen.getByRole("tab", { name: "kindAll 130" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "kindVideo 30" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "kindAudio 0" })).toBeInTheDocument();
});

it("按种类筛、换排序都交给服务端", async () => {
  vi.mocked(listAssetPage).mockResolvedValue(pageOf(0, 60, null, 60));
  renderLibrary();
  await screen.findByRole("button", { name: "a0" });
  await userEvent.click(screen.getByRole("tab", { name: "kindVideo 30" }));
  await waitFor(() => expect(vi.mocked(listAssetPage).mock.calls.at(-1)?.[0]).toMatchObject({ kind: ["video"] }));
});

it("搜索等停手之后才发一次请求", async () => {
  vi.mocked(listAssetPage).mockResolvedValue(pageOf(0, 60, null, 60));
  renderLibrary();
  await screen.findByRole("button", { name: "a0" });
  vi.mocked(listAssetPage).mockClear();
  const box = screen.getByRole("textbox", { name: "searchAssets" });
  fireEvent.change(box, { target: { value: "b" } });
  fireEvent.change(box, { target: { value: "be" } });
  fireEvent.change(box, { target: { value: "beach" } });
  expect(listAssetPage).not.toHaveBeenCalled();
  await waitFor(() => expect(listAssetPage).toHaveBeenCalledTimes(1));
  expect(vi.mocked(listAssetPage).mock.calls[0][0]).toMatchObject({ q: "beach" });
});

//: 「滚到最后几行才取下一页」在 MediaLibraryView.virtual.dom.test.tsx(取下一页跟着只画看得见的那几行走)。

it("全选选的是满足条件的全部,没翻到的几页先取回来", async () => {
  vi.mocked(listAssetPage).mockImplementation(async (_query, cursor) =>
    cursor === "c1" ? pageOf(60, 10, null, 70) : pageOf(0, 60, "c1", 70),
  );
  renderLibrary();
  await screen.findByRole("button", { name: "a0" });
  await userEvent.click(screen.getByRole("button", { name: "mediaSelectMode" }));
  await userEvent.click(screen.getByRole("button", { name: /mediaSelectAll/ }));
  expect(await screen.findByText("selected 70")).toBeInTheDocument();
  expect(vi.mocked(listAssetPage).mock.calls.at(-1)?.[1]).toBe("c1");
});

it("深链点名的那一份直接按 id 打开详情,不等它出现在列表里", async () => {
  window.location.hash = "#/media?asset=far-away";
  vi.mocked(listAssetPage).mockResolvedValue(pageOf(0, 60, "c1", 500));
  vi.mocked(getAsset).mockResolvedValue({ ...card("far-away"), file_key: "", media_info: {}, proxy_expected: false });
  renderLibrary();
  expect(await screen.findByTestId("preview")).toHaveTextContent("far-away");
  expect(getAsset).toHaveBeenCalledWith("far-away");
  expect(window.location.hash).toBe("#/media");
});
