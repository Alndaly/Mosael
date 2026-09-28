/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";

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
vi.mock("@/api/client", () => ({
  listAssets: vi.fn(async () => assets),
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh" }) }));

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
  fireEvent.click(screen.getByRole("button", { name: "boardKindVideo" }));
  await waitFor(() => expect(titles()).toHaveLength(1));
  expect(screen.getByRole("button", { name: "boardKindVideo" }).getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(screen.getAllByRole("option")[0]);
  expect(onPick).toHaveBeenCalledWith("vid", "video");
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
  expect(onPick).toHaveBeenCalledWith("deck", "document");
  cleanup();
  mount("media");
  await waitFor(() => expect(titles()).toHaveLength(3));
  expect(titles().join("|")).not.toContain("方案.pptx");
});
