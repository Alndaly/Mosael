/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";

/**
 * 挑素材的弹窗里看大图:点一行是挑(弹窗就关了),所以看大图是行首缩略图上压的那颗;左右翻的是眼下这份清单里的
 * 图和视频。音频没有画面,不给。
 */

const openImagePreview = vi.hoisted(() => vi.fn());
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview, isImagePreviewOpen: false }) }));

const assets = [
  { id: "img", kind: "image", name: "海报", media_info: { width: 800, height: 600 } },
  { id: "vid", kind: "video", name: "开场", media_info: { duration: 12 } },
  { id: "aud", kind: "audio", name: "旁白", media_info: {} },
];
vi.mock("@/api/client", () => ({
  listAssetPage: vi.fn(async (query: { kind?: string[] }) => {
    const items = assets.filter((one) => !query.kind || query.kind.includes(one.kind));
    return { items, next_cursor: null, total: items.length };
  }),
  getAsset: vi.fn(async (id: string) => assets.find((one) => one.id === id)),
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  assetFileUrl: (id: string) => `/file/${id}`,
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => (key === "viewFullSizeOf" ? "看大图:{name}" : key),
  usePreferences: () => ({ locale: "zh" }),
}));

import { AssetPickerDialog } from "./AssetPickerDialog";

beforeAll(() => {
  Element.prototype.scrollIntoView ??= () => {};
});
afterEach(() => {
  cleanup();
  openImagePreview.mockReset();
});

function mount() {
  const onPick = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AssetPickerDialog open kind="media" workspaceId="ws" onOpenChange={vi.fn()} onPick={onPick} />
    </QueryClientProvider>,
  );
  return onPick;
}

it("图和视频那一行有「看大图」,音频没有", async () => {
  mount();
  await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(3));
  expect(screen.getByRole("button", { name: "看大图:海报" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "看大图:开场" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "看大图:旁白" })).toBeNull();
});

it("「看大图」开灯箱、翻这份清单里的图和视频;这一行不算挑中", async () => {
  const onPick = mount();
  fireEvent.click(await screen.findByRole("button", { name: "看大图:开场" }));
  expect(openImagePreview).toHaveBeenCalledWith({
    src: "/file/vid",
    title: "开场",
    video: true,
    gallery: [
      { src: "/preview/img", title: "海报" },
      { src: "/file/vid", title: "开场", video: true },
    ],
  });
  expect(onPick).not.toHaveBeenCalled();
});

it("点这一行本身仍然是挑", async () => {
  const onPick = mount();
  await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(3));
  fireEvent.click(screen.getAllByRole("option")[0]);
  expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: "img" }));
  expect(openImagePreview).not.toHaveBeenCalled();
});
