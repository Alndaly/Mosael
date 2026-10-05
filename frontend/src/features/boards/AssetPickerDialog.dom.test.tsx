/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
//: 这里不测看大图(那是 image-preview 自己和各处接线测试的事),只给一个桩让组件挂得上。
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn(), isImagePreviewOpen: false }) }));

/**
 * 挑素材的弹窗。「添加 → 从库里放 → 素材」一行挑三种:图片、视频、音频都列,头里按种类筛,挑中哪一种
 * 就交回哪一种(放哪一种格子)。给一格换一份时只列那一类。
 */

const assets = [
  { id: "img", kind: "image", name: "海报", media_info: { width: 800, height: 600 } },
  { id: "vid", kind: "video", name: "开场", media_info: { duration: 12 } },
  { id: "aud", kind: "audio", name: "旁白", media_info: {} },
  { id: "doc", kind: "file", name: "说明.pdf", media_info: {} },
  { id: "deck", kind: "document", name: "方案.pptx", media_info: {} },
];
//: 一个小小的「服务端」:种类在服务端筛(素材库分页之后,不再整个拿回来在弹窗里筛);按 id 取详情。
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
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh" }) }));

import { listAssetPage } from "@/api/client";
import { AssetPickerDialog } from "./AssetPickerDialog";

beforeAll(() => {
  Element.prototype.scrollIntoView ??= () => {};
});
afterEach(cleanup);

function mount(kind: "image" | "media", onPick = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AssetPickerDialog open kind={kind} workspaceId="ws" onOpenChange={vi.fn()} onPick={onPick} />
    </QueryClientProvider>,
  );
  return onPick;
}

const titles = () => [...document.querySelectorAll('[role="option"]')].map((one) => one.textContent ?? "");

it("「素材」一行:图片、视频、音频都列(别的文件不列),按种类筛;挑中的交回它的种类", async () => {
  const onPick = mount("media");
  await waitFor(() => expect(titles()).toHaveLength(3));
  expect(titles().join("|")).not.toContain("说明.pdf");
  expect(vi.mocked(listAssetPage).mock.calls.at(-1)?.[0]).toMatchObject({ workspace_id: "ws", kind: ["image", "video", "audio"] });
  fireEvent.click(screen.getByRole("button", { name: "boardKindVideo" }));
  await waitFor(() => expect(titles()).toHaveLength(1));
  expect(screen.getByRole("button", { name: "boardKindVideo" }).getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(screen.getAllByRole("option")[0]);
  //: 名字一起交回:「添加 → 素材」放下的一格和拖进来的一样写着素材名(boardPlacement.assetFields)。
  expect(onPick).toHaveBeenCalledWith({ id: "vid", name: "开场", kind: "video" });
});

it("给一格换一份:只列那一类,没有筛选条", async () => {
  mount("image");
  await waitFor(() => expect(titles()).toHaveLength(1));
  expect(titles()[0]).toContain("海报");
  expect(screen.queryByRole("group", { name: "boardsPickMediaKind" })).toBeNull();
});

it("时间线格的「+」:先列这张画板上的素材;点掉「这张画板上的」就是整个素材库", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AssetPickerDialog open kind="media" workspaceId="ws" onOpenChange={vi.fn()} onPick={vi.fn()} onBoard={["vid"]} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(titles()).toHaveLength(1));
  expect(titles()[0]).toContain("开场");
  const onBoard = screen.getByRole("button", { name: "boardsPickOnBoard" });
  expect(onBoard.getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(onBoard);
  await waitFor(() => expect(titles()).toHaveLength(3));
});

it("没有画板上的素材就不多那一枚", async () => {
  mount("media");
  await waitFor(() => expect(titles()).toHaveLength(3));
  expect(screen.queryByRole("button", { name: "boardsPickOnBoard" })).toBeNull();
});


it("画板「从库里放」连文档一起列(落成文档格);时间线的「+」不列文档", async () => {
  const onPick = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AssetPickerDialog open kind="media" workspaceId="ws" onOpenChange={vi.fn()} onPick={onPick} withDocuments />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(titles()).toHaveLength(4));
  fireEvent.click(screen.getByRole("button", { name: "kindDocument" }));
  await waitFor(() => expect(titles()).toHaveLength(1));
  fireEvent.click(screen.getAllByRole("option")[0]);
  expect(onPick).toHaveBeenCalledWith({ id: "deck", name: "方案.pptx", kind: "document" });
  cleanup();
  mount("media");
  await waitFor(() => expect(titles()).toHaveLength(3));
  expect(titles().join("|")).not.toContain("方案.pptx");
});
