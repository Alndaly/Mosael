/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

/**
 * 笔记来源是一张图:来源弹窗里那张图点开看大图。用真的灯箱 —— 这是「弹窗里看大图」的第二个现场
 * (挑素材的弹窗是 ModalShell,这里是裸的 Dialog):Esc 先只关大图,再按一下才关弹窗;焦点回到图上。
 */

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  getAsset: vi.fn(async (id: string) => ({ id, kind: "image", name: "白板照片.jpg" })),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { ImagePreviewProvider } from "@/components/app/image-preview";
import { SourceLink } from "./NoteSources";

afterEach(cleanup);

const lightbox = () => document.querySelector<HTMLElement>(".PhotoView-Portal");
const lightboxClosing = () => lightbox()?.classList.contains("PhotoView-Slider__willClose") ?? true;

it("来源弹窗里的图点开看大图;Esc 先关大图、弹窗还在,再按一下才关弹窗", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
        <SourceLink source={{ kind: "asset", id: "photo-1", label: "会议白板", quote: "" }} workspaceId="ws" />
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: /会议白板/ }));
  const zoom = await screen.findByRole("button", { name: "看大图" });
  zoom.focus();
  fireEvent.click(zoom);
  await waitFor(() => expect(lightbox()?.textContent).toContain("会议白板"));

  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  await waitFor(() => expect(lightboxClosing()).toBe(true));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(document.activeElement).toBe(zoom);

  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  //: 弹窗收起(关闭动画期间还在 DOM 里,状态已经是 closed)。
  await waitFor(() => expect(screen.queryByRole("dialog")?.getAttribute("data-state") ?? "closed").toBe("closed"));
});
