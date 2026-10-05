/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import type { BoardItem } from "@/api/client";

/**
 * 「让 AI 写」面板最上面那排引到的素材:点开一张,灯箱里左右翻的是这一格引到的全部图和视频。
 * 音频没有画面 —— 此前它也被塞进灯箱当成一张图去加载,开出来一片空白;现在开素材详情(里面有完整的播放器)。
 */

const assets: Record<string, { id: string; kind: string; name: string }> = {
  img1: { id: "img1", kind: "image", name: "分镜" },
  aud1: { id: "aud1", kind: "audio", name: "旁白" },
  vid1: { id: "vid1", kind: "video", name: "样片" },
};
vi.mock("@/api/client", async () => ({
  getAsset: vi.fn(async (id: string) => assets[id]),
  listCapabilityModels: vi.fn(async () => []),
  listAssetPage: vi.fn(async () => ({ items: [], next_cursor: null, total: 0 })),
  listEntities: vi.fn(async () => []),
  getEntity: vi.fn(),
  ApiError: (await import("@/api/transport")).ApiError,
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  assetFileUrl: (id: string) => `/file/${id}`,
  entityKeys: {
    detail: (ws: string, id: string) => ["entities", ws, "detail", id],
    list: (ws: string, filters: Record<string, unknown> = {}) => ["entities", ws, "list", filters],
  },
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh" }) }));
vi.mock("@xyflow/react", () => ({
  NodeToolbar: ({ children }: { children: React.ReactNode }) => children,
  Position: { Left: "left", Right: "right", Bottom: "bottom" },
  useStore: (selector: (state: { transform: [number, number, number] }) => unknown) => selector({ transform: [0, 0, 1] }),
}));
const openImagePreview = vi.hoisted(() => vi.fn());
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview, isImagePreviewOpen: false }) }));
const detail = vi.hoisted(() => vi.fn());
vi.mock("@/features/media/AssetPreviewModalById", () => ({
  AssetPreviewModalById: ({ id }: { id: string | null }) => {
    detail(id);
    return null;
  },
}));
vi.mock("./PromptEditor", () => ({
  PromptEditor: () => <div data-testid="prompt-editor" />,
  restorePromptDocument: vi.fn(),
  textDocument: vi.fn(),
  collect: () => [],
}));

import { NoteComposer } from "./NoteComposer";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NoteComposer
        item={{ id: "n1", kind: "note", x: 0, y: 0 } as BoardItem}
        busy={false}
        workspaceId="ws"
        upstreamAssets={["img1", "aud1", "vid1"]}
        onWrite={vi.fn()}
        onFormChange={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

it("点开一张图:翻的是这一格引到的图和视频(音频不在里面)", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "样片" }));
  expect(openImagePreview).toHaveBeenCalledWith({
    src: "/file/vid1",
    title: "样片",
    video: true,
    gallery: [
      { src: "/preview/img1", title: "分镜" },
      { src: "/file/vid1", title: "样片", video: true },
    ],
  });
});

it("点音频开素材详情,不进灯箱", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "旁白" }));
  await waitFor(() => expect(detail).toHaveBeenLastCalledWith("aud1"));
  expect(openImagePreview).not.toHaveBeenCalled();
});
