/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";

/**
 * 「从素材库添加」里看大图:点格子是勾选,看大图是格子角上那颗;左右翻的是眼下筛出来的这一屏。
 * 用的是真的灯箱 —— 这里要钉住的正是「在弹窗里看大图」那几件事:Esc 先只关大图,挑到一半的几张还在。
 */

import { ImagePreviewProvider } from "@/components/app/image-preview";
import { listAssetPage, type AssetCard } from "@/api/client";
import { LibraryPickerDialog } from "./LibraryPickerDialog";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => (key === "viewFullSizeOf" ? "看大图:{name}" : key),
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  listAssetPage: vi.fn(),
}));

const card = (id: string, kind: string): AssetCard => ({
  id, name: `${id} 图`, workspace_id: "ws", project_id: null, original_filename: id, kind, source: "imported", tags: [],
  derived: false, ai_generated: false, intermediate: "",
  media_info: { duration: null, width: null, height: null, fps: null, has_thumbnail: true, format: null, pages: null, size_bytes: null },
});

beforeAll(() => {
  Element.prototype.scrollIntoView ??= () => {};
});
afterEach(cleanup);

function mount() {
  const items = [card("front", "image"), card("side", "image"), card("turn", "video")];
  vi.mocked(listAssetPage).mockResolvedValue({ items, next_cursor: null, total: items.length });
  const onOpenChange = vi.fn();
  const onAdd = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
        <LibraryPickerDialog open onOpenChange={onOpenChange} workspaceId="ws" attached={new Set(["side"])} pending={false} onAdd={onAdd} />
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
  return { onOpenChange, onAdd };
}

const lightbox = () => document.querySelector<HTMLElement>(".PhotoView-Portal");
const lightboxClosing = () => lightbox()?.classList.contains("PhotoView-Slider__willClose") ?? true;

it("「看大图」开灯箱、从这一张开始翻这一屏;不勾选这一格", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "看大图:turn 图" }));
  await waitFor(() => expect(lightbox()).not.toBeNull());
  expect(lightbox()!.textContent).toContain("3 / 3");
  expect(lightbox()!.textContent).toContain("turn 图");
  expect(screen.getByRole("option", { name: "turn 图" })).toHaveAttribute("aria-selected", "false");
});

it("已经挂上的那张不能再选,但能看大图", async () => {
  mount();
  const attached = await screen.findByRole("option", { name: "side 图" });
  //: 点不动,但键盘还走得到(网格里的格子不从 Tab 顺序里消失,读屏念得出它「不可用」)。
  expect(attached).toHaveAttribute("aria-disabled", "true");
  fireEvent.click(attached);
  expect(attached).toHaveAttribute("aria-selected", "false");
  fireEvent.click(screen.getByRole("button", { name: "看大图:side 图" }));
  await waitFor(() => expect(lightbox()?.textContent).toContain("2 / 3"));
});

it("弹窗里:Esc 先只关大图,勾好的还在;再按一下才关弹窗", async () => {
  const { onOpenChange } = mount();
  fireEvent.click(await screen.findByRole("option", { name: "front 图" }));
  expect(screen.getByRole("option", { name: "front 图" })).toHaveAttribute("aria-selected", "true");

  const zoom = screen.getByRole("button", { name: "看大图:front 图" });
  zoom.focus();
  fireEvent.click(zoom);
  await waitFor(() => expect(lightbox()).not.toBeNull());

  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  await waitFor(() => expect(lightboxClosing()).toBe(true));
  expect(onOpenChange).not.toHaveBeenCalled();
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByRole("option", { name: "front 图" })).toHaveAttribute("aria-selected", "true");
  //: 焦点回到「看大图」那颗上 —— 还在弹窗里,接着挑。
  expect(document.activeElement).toBe(zoom);

  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  expect(onOpenChange).toHaveBeenCalledWith(false);
});
