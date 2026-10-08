/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
//: 这里不测看大图(那是 image-preview 自己和各处接线测试的事),只给一个桩让组件挂得上。
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn(), isImagePreviewOpen: false }) }));
import { getAssetFacets, listAssetPage, separateAssetAudio, type AssetCard, type AssetQuery, type Workspace } from "@/api/client";
import { gotoSection } from "@/lib/deepLink";
import { MediaLibraryView } from "./MediaLibraryView";
import { readHint } from "@/test/hint";

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  separateAssetAudio: vi.fn(async () => ({ id: "job-1" })),
  listAssetPage: vi.fn(),
  getAssetFacets: vi.fn(async () => ({ total: 0, kinds: {}, tags: {}, intermediates: {} })),
}));

const asset = (id: string, kind: string, tags: string[] = []): AssetCard => ({
  id, name: id, workspace_id: "ws", project_id: null, original_filename: id, kind, source: "imported", tags,
  derived: false, ai_generated: false, intermediate: "",
  media_info: { duration: null, width: null, height: null, fps: null, has_thumbnail: false, format: null, pages: null, size_bytes: null },
});

/** 素材库里就是这几份:种类、标签在服务端筛(和真的一样,一页交回)。 */
function serve(cards: AssetCard[]) {
  vi.mocked(listAssetPage).mockImplementation(async (query: AssetQuery) => {
    const items = cards.filter(
      (one) => (!query.kind || query.kind.includes(one.kind)) && (query.tag ?? []).every((tag) => one.tags?.includes(tag)),
    );
    return { items, next_cursor: null, total: items.length };
  });
  const count = (values: string[]) => Object.fromEntries([...new Set(values)].map((one) => [one, values.filter((v) => v === one).length]));
  vi.mocked(getAssetFacets).mockResolvedValue({
    total: cards.length,
    kinds: count(cards.map((one) => one.kind)),
    tags: count(cards.flatMap((one) => one.tags ?? [])),
    intermediates: {},
  });
}
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "en" }) }));
vi.mock("@/features/media/recordingContext", () => ({ useRecorder: () => ({ openRecorder: vi.fn() }) }));
vi.mock("@/features/media/UrlImportDialog", () => ({ UrlImportDialog: () => null }));
vi.mock("@/features/media/AssetPreviewModal", () => ({ AssetPreviewModal: () => null }));

it("keeps only the current asset action menu open and closes it for a context menu", async () => {
  localStorage.clear();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  serve(["one", "two", "three"].map((id) => asset(id, "image")));
  render(<QueryClientProvider client={client}><MediaLibraryView workspace={{ id: "ws", role: "editor" } as Workspace} /></QueryClientProvider>);
  const user = userEvent.setup();
  await screen.findByRole("button", { name: "studioActions: one" });
  for (const id of ["one", "two", "three"]) {
    await user.click(screen.getByRole("button", { name: `studioActions: ${id}` }));
    await waitFor(() => expect(screen.getAllByRole("menuitem", { name: "rename" })).toHaveLength(1));
    expect(screen.getByRole("button", { name: `studioActions: ${id}` })).toHaveAttribute("aria-expanded", "true");
  }
  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("menuitem", { name: "rename" })).not.toBeInTheDocument());
  await user.click(screen.getByRole("button", { name: "studioActions: one" }));
  fireEvent.contextMenu(screen.getByRole("button", { name: "two" }), { button: 2, clientX: 50, clientY: 50 });
  // ⋯ 菜单(叫 studioActions 的那张)收起,只剩右键菜单里的那一个「重命名」。
  await waitFor(() => expect(screen.queryByRole("menu", { name: "studioActions" })).not.toBeInTheDocument());
  expect(screen.getByRole("menuitem", { name: "rename" })).toBeInTheDocument();
});

it("有声音的素材才能分离人声与背景音,点了就排任务", async () => {
  localStorage.clear();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  serve([asset("clip", "video"), asset("still", "image")]);
  render(<QueryClientProvider client={client}><MediaLibraryView workspace={{ id: "ws", role: "editor" } as Workspace} /></QueryClientProvider>);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "studioActions: still" }));
  await waitFor(() => expect(screen.getByRole("menuitem", { name: "rename" })).toBeInTheDocument());
  expect(screen.queryByRole("menuitem", { name: "separateAudio" })).not.toBeInTheDocument();
  expect(screen.queryByRole("menuitem", { name: "denoiseAction" })).not.toBeInTheDocument();
  await user.keyboard("{Escape}");

  await user.click(screen.getByRole("button", { name: "studioActions: clip" }));
  await user.click(await screen.findByRole("menuitem", { name: "separateAudio" }));
  await waitFor(() => expect(separateAssetAudio).toHaveBeenCalledWith("clip"));
});

it("有声音的素材能降噪:点了打开降噪对话框", async () => {
  localStorage.clear();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  serve([asset("clip", "audio")]);
  client.setQueryData(["denoise-engines"], []);
  render(<QueryClientProvider client={client}><MediaLibraryView workspace={{ id: "ws", role: "editor" } as Workspace} /></QueryClientProvider>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "studioActions: clip" }));
  await user.click(await screen.findByRole("menuitem", { name: "denoiseAction" }));
  expect(await screen.findByRole("dialog", { name: "denoiseTitle" })).toBeInTheDocument();
});

// 统计页「素材 N」点进来:看的是全部 N 个 —— 记住的类型 / 标签筛选这回不作数(也不再记着)。
it("从起点进来时清掉记住的类型和标签筛选", async () => {
  localStorage.clear();
  localStorage.setItem("mosael:tab:media-kind", "video");
  localStorage.setItem("mosael:selected-set:media-tags", JSON.stringify(["b-roll"]));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  serve([asset("clip", "video", ["b-roll"]), asset("still", "image", [])]);
  gotoSection("media");
  render(<QueryClientProvider client={client}><MediaLibraryView workspace={{ id: "ws", role: "editor" } as Workspace} /></QueryClientProvider>);
  expect(await screen.findByRole("button", { name: "still" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "clip" })).toBeInTheDocument();
  expect(localStorage.getItem("mosael:tab:media-kind")).toBe("all");
  expect(localStorage.getItem("mosael:selected-set:media-tags")).toBeNull();
});

//: 只读成员(体检 UM-20 / D62):写的入口都是灰的、说清为什么(和定时任务页同一个做法);下载这类只读的照常能点。
it("只读成员:导入和改素材的条目是灰的、说为什么;下载照常能点", async () => {
  localStorage.clear();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  serve([asset("clip", "video")]);
  render(<QueryClientProvider client={client}><MediaLibraryView workspace={{ id: "ws", role: "viewer" } as Workspace} /></QueryClientProvider>);
  const user = userEvent.setup();

  const importButton = await screen.findByRole("button", { name: "import" });
  expect(importButton).toBeDisabled();
  expect(await readHint(importButton)).toBe("roleReadOnlyHint");
  expect(screen.getByRole("button", { name: "record" })).toBeDisabled();

  await user.click(await screen.findByRole("button", { name: "studioActions: clip" }));
  const rename = await screen.findByRole("menuitem", { name: "rename" });
  expect(rename).toBeDisabled();
  expect(rename).toHaveAccessibleDescription("roleReadOnlyBrief");
  expect(screen.getByRole("menuitem", { name: "delete" })).toBeDisabled();
  expect(screen.getByRole("menuitem", { name: "separateAudio" })).toBeDisabled();
  expect(screen.getByRole("menuitem", { name: "assetSaveLocal" })).toBeEnabled();
  await user.keyboard("{Escape}");

  fireEvent.contextMenu(screen.getByRole("button", { name: "clip" }), { button: 2, clientX: 50, clientY: 50 });
  expect(await screen.findByRole("menuitem", { name: /^delete/ })).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByRole("menuitem", { name: /^assetSaveLocal/ })).not.toHaveAttribute("aria-disabled");
});

it("编辑及以上:同一批入口照常能点", async () => {
  localStorage.clear();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  serve([asset("clip", "video")]);
  render(<QueryClientProvider client={client}><MediaLibraryView workspace={{ id: "ws", role: "editor" } as Workspace} /></QueryClientProvider>);
  const user = userEvent.setup();
  expect(await screen.findByRole("button", { name: "import" })).toBeEnabled();
  await user.click(await screen.findByRole("button", { name: "studioActions: clip" }));
  expect(await screen.findByRole("menuitem", { name: "rename" })).toBeEnabled();
  expect(screen.getByRole("menuitem", { name: "delete" })).toBeEnabled();
});
