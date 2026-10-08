/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

/**
 * 素材库里看大图。点卡片是开详情(尺寸、来源、标签),勾选模式里是勾选 —— 看大图于是是缩略图角上单独一颗,
 * 左右翻的是**眼下这一格网格**:同样的筛选、同样的排序里的图和视频(音频、文档没有画面,不进来)。
 */

const openImagePreview = vi.hoisted(() => vi.fn());
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview, isImagePreviewOpen: false }) }));

import { assetFileUrl, assetPreviewUrl, getAssetFacets, listAssetPage, type AssetCard, type Workspace } from "@/api/client";
import { MediaLibraryView } from "./MediaLibraryView";

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  listAssetPage: vi.fn(),
  getAssetFacets: vi.fn(),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => (key === "viewFullSizeOf" ? "看大图:{name}" : key),
  usePreferences: () => ({ locale: "en" }),
}));
vi.mock("@/features/media/recordingContext", () => ({ useRecorder: () => ({ openRecorder: vi.fn() }) }));
vi.mock("@/features/media/UrlImportDialog", () => ({ UrlImportDialog: () => null }));
const detail = vi.hoisted(() => vi.fn());
const closeDetail = vi.hoisted(() => ({ current: () => {} }));
vi.mock("@/features/media/AssetPreviewModalById", () => ({
  AssetPreviewModalById: ({ id, onClose }: { id: string | null; onClose: () => void }) => {
    detail(id);
    closeDetail.current = onClose;
    return null;
  },
}));

const card = (id: string, kind: string): AssetCard => ({
  id, name: `${id} 名字`, workspace_id: "ws", project_id: null, original_filename: id, kind, source: "imported", tags: [],
  derived: false, ai_generated: false, intermediate: "",
  media_info: { duration: null, width: null, height: null, fps: null, has_thumbnail: false, format: null, pages: null, size_bytes: null },
});

const cards = [card("poster", "image"), card("voice", "audio"), card("clip", "video"), card("still", "image")];

function mount() {
  localStorage.clear();
  vi.mocked(listAssetPage).mockImplementation(async () => ({ items: cards, next_cursor: null, total: cards.length }));
  vi.mocked(getAssetFacets).mockResolvedValue({ total: cards.length, kinds: { image: 2, audio: 1, video: 1 }, tags: {}, intermediates: {} });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  render(<QueryClientProvider client={client}><MediaLibraryView workspace={{ id: "ws" } as Workspace} /></QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  openImagePreview.mockReset();
  detail.mockReset();
});

const grid = [
  { src: assetPreviewUrl("poster"), title: "poster 名字" },
  { src: assetFileUrl("clip"), title: "clip 名字", video: true },
  { src: assetPreviewUrl("still"), title: "still 名字" },
];

it("图和视频的卡片上各有一颗「看大图」,音频没有", async () => {
  mount();
  await screen.findByRole("button", { name: "看大图:poster 名字" });
  expect(screen.getByRole("button", { name: "看大图:clip 名字" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "看大图:still 名字" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "看大图:voice 名字" })).toBeNull();
});

it("「看大图」开灯箱,从这一张开始翻眼下这格网格;不开详情", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "看大图:clip 名字" }));
  expect(openImagePreview).toHaveBeenCalledWith({ src: assetFileUrl("clip"), title: "clip 名字", video: true, gallery: grid });
  expect(detail).not.toHaveBeenCalledWith("clip");
});

it("点卡片本身照旧开详情,不开灯箱", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "still 名字" }));
  await waitFor(() => expect(detail).toHaveBeenCalledWith("still"));
  expect(openImagePreview).not.toHaveBeenCalled();
});

//: 体检 UM-24:键盘关掉详情之后焦点掉回 body,几百张的网格里得从顶上重新 Tab。
it("关掉详情,焦点回到打开它的那张卡上", async () => {
  mount();
  const opener = await screen.findByRole("button", { name: "still 名字" });
  opener.focus();
  fireEvent.click(opener);
  await waitFor(() => expect(detail).toHaveBeenCalledWith("still"));
  (document.activeElement as HTMLElement | null)?.blur();
  act(() => closeDetail.current());
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "still 名字" })));
});

it("勾选模式里点「看大图」只看,不勾选", async () => {
  mount();
  await screen.findByRole("button", { name: "看大图:poster 名字" });
  fireEvent.click(screen.getByRole("button", { name: "mediaSelectMode" }));
  fireEvent.click(screen.getByRole("button", { name: "看大图:poster 名字" }));
  expect(openImagePreview).toHaveBeenCalledTimes(1);
  //: 一份都没勾上:批量「加标签」还是灰的。点卡片本身才勾 —— 勾上之后它就亮了(证明这个判据看得出区别)。
  expect(screen.getByRole("button", { name: "addTags" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "poster 名字" }));
  expect(screen.getByRole("button", { name: "addTags" })).toBeEnabled();
});
