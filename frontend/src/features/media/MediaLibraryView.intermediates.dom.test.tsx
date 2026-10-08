/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
//: 这里不测看大图(那是 image-preview 自己和各处接线测试的事),只给一个桩让组件挂得上。
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn(), isImagePreviewOpen: false }) }));
import { getAssetFacets, listAssetPage, type AssetCard, type AssetQuery, type Workspace } from "@/api/client";
import { gotoSection } from "@/lib/deepLink";
import { MediaLibraryView } from "./MediaLibraryView";

/**
 * 中间产物(逐句配音的一句……)素材库默认不列,但找得到:筛选条上一枚「配音片段 985」,按下去看的就是它们,
 * 上面一句话说清它们是什么、时间线上照常在用,一键回到素材库。
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

const card = (id: string, intermediate = "", lineText: string | null = null): AssetCard => ({
  id, name: intermediate ? "zh-TW-HsiaoChenNeural · 配音" : id, workspace_id: "ws", project_id: null,
  original_filename: `${id}.mp3`, kind: "audio", source: intermediate ? "tts" : "imported", tags: [], derived: false,
  ai_generated: Boolean(intermediate), intermediate, created_at: "2026-01-01T00:00:00", updated_at: "2026-01-01T00:00:00",
  media_info: { duration: 2, width: null, height: null, fps: null, has_thumbnail: false, format: null, pages: null, size_bytes: null, line_text: lineText },
});

/** 一个小小的「服务端」:素材库 3 份,配音片段 2 份;按 intermediate 分开列、分开数。 */
function serve() {
  const library = [card("narration"), card("music"), card("voiceover")];
  const lines = [card("l1", "dub_line", "Okay, so today we talk about control net"), card("l2", "dub_line", "points in the picture")];
  vi.mocked(listAssetPage).mockImplementation(async (query: AssetQuery) => {
    const items = query.intermediate === "dub_line" ? lines : library;
    return { items, next_cursor: null, total: items.length };
  });
  vi.mocked(getAssetFacets).mockImplementation(async (_ws: string, _project?: string | null, intermediate?: string) =>
    intermediate === "dub_line"
      ? { total: 2, kinds: { audio: 2 }, tags: {}, intermediates: { dub_line: 985 } }
      : { total: 3, kinds: { audio: 3 }, tags: {}, intermediates: { dub_line: 985 } });
}

beforeEach(() => {
  localStorage.clear();
  window.location.hash = "#/media";
  vi.mocked(listAssetPage).mockReset();
  vi.mocked(getAssetFacets).mockReset();
  serve();
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

it("默认只看素材库;筛选条上写着配音片段有几份", async () => {
  renderLibrary();
  expect(await screen.findByRole("button", { name: "narration" })).toBeInTheDocument();
  expect(vi.mocked(listAssetPage).mock.calls[0][0].intermediate ?? "").toBe("");
  const shelf = await screen.findByRole("button", { name: "mediaIntermediate_dub_line 985" });
  expect(shelf).toHaveAttribute("aria-pressed", "false");
  expect(screen.queryByText("mediaIntermediateHint_dub_line")).toBeNull();
});

it("按下去看的是配音片段:页签数字跟着变,说清它们在时间线上照常用,能一键回到素材库", async () => {
  const user = userEvent.setup();
  renderLibrary();
  await user.click(await screen.findByRole("button", { name: "mediaIntermediate_dub_line 985" }));
  //: 这些片段的名字都一样,读屏念的名字带上念的那句话。
  expect(await screen.findByRole("button", { name: /control net$/ })).toBeInTheDocument();
  expect(vi.mocked(listAssetPage).mock.calls.at(-1)?.[0]).toMatchObject({ intermediate: "dub_line" });
  expect(vi.mocked(getAssetFacets).mock.calls.at(-1)?.[2]).toBe("dub_line");
  expect(await screen.findByRole("tab", { name: "kindAll 2" })).toBeInTheDocument();
  //: 标题旁的数说的还是素材库:看配音片段时写着「素材 985」,会让人以为素材库里就是这些。
  expect(screen.getByRole("heading", { name: "navMedia" }).nextElementSibling).toHaveTextContent("3");
  expect(screen.getByRole("button", { name: "mediaIntermediate_dub_line 985" })).toHaveAttribute("aria-pressed", "true");
  //: 卡片上写着念的是哪一句 —— 这些片段的名字都一样。
  expect(screen.getByText("Okay, so today we talk about control net")).toBeInTheDocument();
  expect(screen.getByText("mediaIntermediateHint_dub_line")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "mediaBackToLibrary" }));
  expect(await screen.findByRole("button", { name: "narration" })).toBeInTheDocument();
  expect(screen.queryByText("mediaIntermediateHint_dub_line")).toBeNull();
});

it("从起点进来(统计页的素材总数)看的是素材库,不停在配音片段上", async () => {
  const user = userEvent.setup();
  renderLibrary();
  await user.click(await screen.findByRole("button", { name: "mediaIntermediate_dub_line 985" }));
  await screen.findByRole("button", { name: /control net$/ });
  act(() => gotoSection("media"));
  expect(await screen.findByRole("button", { name: "narration" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "mediaIntermediate_dub_line 985" })).toHaveAttribute("aria-pressed", "false");
});

it("一份中间产物都没有就不摆这枚", async () => {
  vi.mocked(getAssetFacets).mockResolvedValue({ total: 3, kinds: { audio: 3 }, tags: {}, intermediates: {} });
  renderLibrary();
  await screen.findByRole("button", { name: "narration" });
  await waitFor(() => expect(getAssetFacets).toHaveBeenCalled());
  expect(screen.queryByRole("button", { name: /mediaIntermediate_/ })).toBeNull();
});
