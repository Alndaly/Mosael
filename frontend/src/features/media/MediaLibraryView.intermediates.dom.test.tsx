/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn(), isImagePreviewOpen: false }) }));
import { getAssetFacets, listAssetPage, type AssetCard, type Workspace } from "@/api/client";
import { MediaLibraryView } from "./MediaLibraryView";

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
  id, name: id, workspace_id: "ws", project_id: null,
  original_filename: `${id}.mp3`, kind: "audio", source: "imported", tags: [], derived: false,
  ai_generated: false, intermediate: "", created_at: "2026-01-01T00:00:00", updated_at: "2026-01-01T00:00:00",
  file_missing: false,
  media_info: { duration: 2, width: null, height: null, fps: null, has_thumbnail: false, format: null, pages: null, size_bytes: null, line_text: null },
});

beforeEach(() => {
  localStorage.clear();
  window.location.hash = "#/media";
  vi.mocked(listAssetPage).mockReset().mockImplementation(async () => ({
    items: [card("narration"), card("music"), card("voiceover")], next_cursor: null, total: 3,
  }));
  vi.mocked(getAssetFacets).mockReset().mockResolvedValue({
    total: 3,
    kinds: { audio: 3 },
    tags: {},
  });
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

it("中间产物不在素材库另设筛选入口", async () => {
  renderLibrary();
  expect(await screen.findByRole("button", { name: "narration" })).toBeInTheDocument();
  await waitFor(() => expect(getAssetFacets).toHaveBeenCalled());

  expect(screen.queryByRole("button", { name: /mediaIntermediate_/ })).toBeNull();
  expect(screen.getAllByRole("tab")).toHaveLength(5);
  expect(vi.mocked(listAssetPage).mock.calls.every(([query]) => !query.intermediate)).toBe(true);
  expect(vi.mocked(getAssetFacets).mock.calls.every(([, , intermediate]) => !intermediate)).toBe(true);
});
