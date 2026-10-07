/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
//: 这里不测看大图(那是 image-preview 自己和各处接线测试的事),只给一个桩让组件挂得上。
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn(), isImagePreviewOpen: false }) }));

/**
 * 挑素材的弹窗。「添加 → 从库里放 → 素材」一行挑三种:图片、视频、音频都列,头里一组分段按种类筛,挑中哪一种
 * 就交回哪一种(放哪一种格子)。给一格换一份时只列那一类。网格本身(格子、键盘、空态)见 AssetGridPicker 的测试。
 */

const assets = [
  { id: "img", kind: "image", name: "海报", media_info: { width: 800, height: 600 } },
  { id: "vid", kind: "video", name: "开场", media_info: { duration: 12 } },
  { id: "aud", kind: "audio", name: "旁白", media_info: {} },
  { id: "doc", kind: "file", name: "说明.pdf", media_info: {} },
  { id: "deck", kind: "document", name: "方案.pptx", media_info: {} },
];
//: 一个小小的「服务端」:种类在服务端筛(素材库分页之后,不再整个拿回来在弹窗里筛);按 id 取详情。
async function servePage(query: { kind?: string[] }) {
  const items = assets.filter((one) => !query.kind || query.kind.includes(one.kind));
  return { items, next_cursor: null, total: items.length };
}
async function serveAsset(id: string) {
  return assets.find((one) => one.id === id);
}
vi.mock("@/api/client", () => ({
  listAssetPage: vi.fn(servePage),
  getAsset: vi.fn(serveAsset),
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  assetFileUrl: (id: string) => `/file/${id}`,
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh" }) }));

import { getAsset, listAssetPage } from "@/api/client";
import { AssetPickerDialog } from "./AssetPickerDialog";

beforeAll(() => {
  Element.prototype.scrollIntoView ??= () => {};
});
afterEach(() => {
  cleanup();
  //: 改过「服务端」的那几条之后,换回原来那个。
  vi.mocked(listAssetPage).mockImplementation(servePage as never);
  vi.mocked(getAsset).mockImplementation(serveAsset as never);
});

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
  //: 按种类筛是全应用那一种分段(一组单选),不是一排各自按下的按钮。
  const kinds = screen.getByRole("radiogroup", { name: "boardsPickMediaKind" });
  expect(within(kinds).getAllByRole("radio").map((one) => one.textContent)).toEqual(["boardsPickMediaAll", "boardKindImage", "boardKindVideo", "boardKindAudio"]);
  fireEvent.click(within(kinds).getByRole("radio", { name: "boardKindVideo" }));
  await waitFor(() => expect(titles()).toHaveLength(1));
  expect(within(kinds).getByRole("radio", { name: "boardKindVideo" }).getAttribute("aria-checked")).toBe("true");
  fireEvent.click(screen.getAllByRole("option")[0]);
  //: 名字一起交回:「添加 → 素材」放下的一格和拖进来的一样写着素材名(boardPlacement.assetFields)。
  expect(onPick).toHaveBeenCalledWith({ id: "vid", name: "开场", kind: "video" });
});

it("给一格换一份:只列那一类,没有按种类筛的那一组", async () => {
  mount("image");
  await waitFor(() => expect(titles()).toHaveLength(1));
  expect(titles()[0]).toContain("海报");
  expect(screen.queryByRole("radiogroup", { name: "boardsPickMediaKind" })).toBeNull();
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
  fireEvent.click(screen.getByRole("radio", { name: "kindDocument" }));
  await waitFor(() => expect(titles()).toHaveLength(1));
  fireEvent.click(screen.getAllByRole("option")[0]);
  expect(onPick).toHaveBeenCalledWith({ id: "deck", name: "方案.pptx", kind: "document" });
  cleanup();
  mount("media");
  await waitFor(() => expect(titles()).toHaveLength(3));
  expect(titles().join("|")).not.toContain("方案.pptx");
});

it("「这张画板上的」那几份也是最新的在前,和素材库一个顺序", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(getAsset).mockImplementation(async (id: string) => {
    const one = assets.find((asset) => asset.id === id)!;
    return { ...one, created_at: id === "img" ? "2026-10-07T10:00:00" : "2026-10-01T10:00:00" } as never;
  });
  render(
    <QueryClientProvider client={client}>
      <AssetPickerDialog open kind="media" workspaceId="ws" onOpenChange={vi.fn()} onPick={vi.fn()} onBoard={["vid", "img"]} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(titles()).toHaveLength(2));
  expect(screen.getAllByRole("option").map((one) => one.getAttribute("aria-label"))).toEqual(["海报", "开场"]);
});

it("空着要分清:库里还没有这一种(说可以直接传),还是搜完没有", async () => {
  vi.mocked(listAssetPage).mockImplementation(async () => ({ items: [], next_cursor: null, total: 0 }));
  mount("image");
  expect(await screen.findByText("boardsNoImages")).toBeInTheDocument();
  expect(screen.getByText("boardsPickEmptyHint")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", { name: "boardsSearchImages" }), { target: { value: "日落" } });
  expect(await screen.findByText("studioNoMatches")).toBeInTheDocument();
  expect(screen.queryByText("boardsPickEmptyHint")).toBeNull();
});

