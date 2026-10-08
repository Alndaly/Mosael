/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

/**
 * 删不掉的素材(还在发布中,后端回 409 并说在发到哪个账号):删的地方单独说一句「这份素材现在删不了」加原因,只有「知道了」。
 *
 * 此前原因塞进「确认删除?」那个框里:标题还问着要不要删、红色的「确认」还在,再点只是又被拒一次;一次删好几份时
 * 失败的那几行也落在同一个框里。素材库(单删、批量)、剪辑页素材面板三处同一个说法。
 */

import { ApiError } from "@/api/transport";
import { deleteAsset, getAssetFacets, listAssetPage, type AssetCard, type AssetQuery, type Workspace } from "@/api/client";
import { MediaLibraryView } from "./MediaLibraryView";
import { MediaPool } from "@/features/editor/MediaPool";

const REFUSED = "「成片A」还在发布到「主号」:等它发完,或先在发布页取消那条任务,再删";

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  listAssetPage: vi.fn(),
  getAssetFacets: vi.fn(),
  listDenoiseEngines: vi.fn(async () => []),
  deleteAsset: vi.fn(),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn(), isImagePreviewOpen: false }) }));
vi.mock("@/features/media/recordingContext", () => ({ useRecorder: () => ({ openRecorder: vi.fn() }) }));
vi.mock("@/features/media/UrlImportDialog", () => ({ UrlImportDialog: () => null }));
const detailActions = vi.hoisted(() => ({ current: null as null | ((asset: unknown) => Array<{ label: string; onSelect: () => void }>) }));
vi.mock("@/features/media/AssetPreviewModalById", () => ({
  AssetPreviewModalById: ({ actions }: { actions?: (asset: unknown) => Array<{ label: string; onSelect: () => void }> }) => {
    detailActions.current = actions ?? null;
    return null;
  },
}));

const card = (id: string, name: string): AssetCard => ({
  id, name, workspace_id: "ws", project_id: "p", original_filename: name, kind: "video", source: "imported", tags: [],
  derived: false, ai_generated: false, intermediate: "",
  media_info: { duration: null, width: null, height: null, fps: null, has_thumbnail: false, format: null, pages: null, size_bytes: null },
});
const CARDS = [card("a", "成片A"), card("b", "成片B")];

function serveAssets() {
  vi.mocked(listAssetPage).mockImplementation(async (_query: AssetQuery) => ({ items: CARDS, next_cursor: null, total: CARDS.length }));
  vi.mocked(getAssetFacets).mockResolvedValue({ total: CARDS.length, kinds: { video: 2 }, tags: {}, intermediates: {} });
  //: 「成片A」还在发布:后端回 409,detail 是那一句;「成片B」照常删掉。
  vi.mocked(deleteAsset).mockImplementation(async (id: string) => {
    if (id === "a") throw new ApiError(REFUSED, 409, JSON.stringify({ detail: REFUSED }));
    return undefined;
  });
}

const client = () => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });

afterEach(() => {
  cleanup();
  vi.mocked(deleteAsset).mockReset();
  localStorage.clear();
});

async function expectRefusedNotice(title: string, ...lines: string[]) {
  const notice = (await screen.findByText(title)).closest("[role='alertdialog']") as HTMLElement;
  expect(notice).not.toBeNull();
  for (const line of lines) expect(notice).toHaveTextContent(line);
  expect(within(notice).queryByRole("button", { name: "confirm" })).toBeNull();
  expect(screen.queryByText("deleteConfirmTitle")).toBeNull();
  fireEvent.click(within(notice).getByRole("button", { name: "noticeGotIt" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
}

it("素材库单删:被拒时确认框关掉,单独说删不了和原因,只有「知道了」", async () => {
  serveAssets();
  render(<QueryClientProvider client={client()}><MediaLibraryView workspace={{ id: "ws", role: "owner" } as Workspace} /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "成片A" }));
  await waitFor(() => expect(detailActions.current).not.toBeNull());
  act(() => detailActions.current!(CARDS[0]).at(-1)!.onSelect());
  fireEvent.click(await screen.findByRole("button", { name: "confirm" }));

  await expectRefusedNotice("deleteAssetRefusedTitle", REFUSED);
  expect(deleteAsset).toHaveBeenCalledTimes(1);
});

it("素材库批量删:删掉能删的,删不掉的列出来、各带原因", async () => {
  serveAssets();
  render(<QueryClientProvider client={client()}><MediaLibraryView workspace={{ id: "ws", role: "owner" } as Workspace} /></QueryClientProvider>);
  await screen.findByRole("button", { name: "成片A" });
  fireEvent.click(screen.getByRole("button", { name: "mediaSelectMode" }));
  fireEvent.click(screen.getByRole("button", { name: "成片A" }));
  fireEvent.click(screen.getByRole("button", { name: "成片B" }));
  fireEvent.click(screen.getByRole("button", { name: "delete" }));
  fireEvent.click(await screen.findByRole("button", { name: "confirm" }));

  await screen.findByText("deleteAssetsPartlyRefusedTitle");
  expect(screen.getByText(REFUSED)).toBeInTheDocument(); // 原因里点了名,前面不再重复一遍「成片A: 」
  await expectRefusedNotice("deleteAssetsPartlyRefusedTitle", REFUSED);
  expect(vi.mocked(deleteAsset).mock.calls.map(([id]) => id).sort()).toEqual(["a", "b"]);
});

it("剪辑页素材面板:同一个说法,确认框不留着让人再点一次", async () => {
  serveAssets();
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={client()}>
      <MediaPool workspaceId="ws" projectId="p" uploading={false} onImportFiles={vi.fn()} onRecord={vi.fn()} onAddToTimeline={vi.fn()} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(document.querySelector("[data-pool-item='a']")).not.toBeNull());
  fireEvent.contextMenu(document.querySelector("[data-pool-item='a']")!, { button: 2, clientX: 10, clientY: 10 });
  await user.click(await screen.findByRole("menuitem", { name: "delete" }));
  fireEvent.click(await screen.findByRole("button", { name: "confirm" }));

  await expectRefusedNotice("deleteAssetRefusedTitle", REFUSED);
  expect(deleteAsset).toHaveBeenCalledTimes(1);
});
