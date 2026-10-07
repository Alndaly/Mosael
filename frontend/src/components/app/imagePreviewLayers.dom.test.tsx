/** @vitest-environment jsdom */
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 灯箱压在别的层上面时,一下 Esc、一下点击只归灯箱。
 *
 * 用户看到的那一版:在「从素材库添加」弹窗里看大图,按 Esc 想关掉大图 —— 大图关了,弹窗也一起没了,
 * 挑到一半的几张全丢;点灯箱上的「×」、左右箭头也一样(Radix 把那一下当成「点了弹窗外面」)。
 * 画板的面板、工作流检查器在 window 上听 Esc,同样会被这一下顺手关掉。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { ImagePreviewProvider, useImagePreview } from "@/components/app/image-preview";
import { requestImagePreview } from "@/components/app/image-preview-request";
import { ModalShell } from "@/components/app/modals";

const gallery = [
  { src: "/preview/a", title: "第一张" },
  { src: "/preview/b", title: "第二张" },
];

function Opener() {
  const { openImagePreview } = useImagePreview();
  return (
    <button type="button" onClick={() => openImagePreview({ ...gallery[1], gallery })}>
      看大图
    </button>
  );
}

function DialogWithPreview({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
  return (
    <ModalShell open onOpenChange={onOpenChange} title="从素材库添加">
      <Opener />
    </ModalShell>
  );
}

const portal = () => document.querySelector<HTMLElement>(".PhotoView-Portal");
const closing = () => portal()?.classList.contains("PhotoView-Slider__willClose") ?? true;

async function openFromDialog() {
  const onOpenChange = vi.fn();
  render(
    <ImagePreviewProvider>
      <DialogWithPreview onOpenChange={onOpenChange} />
    </ImagePreviewProvider>,
  );
  const opener = screen.getByRole("button", { name: "看大图" });
  opener.focus();
  fireEvent.click(opener);
  await waitFor(() => expect(portal()).not.toBeNull());
  return { onOpenChange, opener };
}

afterEach(cleanup);

describe("灯箱压在弹窗上面", () => {
  it("从点开的那一张开始,翻的是同一组", async () => {
    await openFromDialog();
    expect(portal()?.textContent).toContain("2 / 2");
    expect(portal()?.textContent).toContain("第二张");
  });

  it("第一下 Esc 只关灯箱,弹窗还在;第二下才轮到弹窗", async () => {
    const { onOpenChange } = await openFromDialog();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await waitFor(() => expect(closing()).toBe(true));
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("在灯箱上按下不算点了弹窗外面 —— 中键点「打开原图」(新标签页里看原图)也不关底下的弹窗", async () => {
    const { onOpenChange } = await openFromDialog();
    //: Radix 等 setTimeout(0) 之后才开始听「点了外面」。
    await new Promise((resolve) => setTimeout(resolve, 10));
    //: 中键、右键的按下 Radix 是立刻判的(左键要等到 click,而灯箱自己会拦下 click 的冒泡)。
    const original = portal()!.querySelector<HTMLAnchorElement>('a[href="/preview/b"]')!;
    fireEvent.pointerDown(original, { button: 1 });
    fireEvent.mouseDown(original, { button: 1 });
    expect(onOpenChange).not.toHaveBeenCalled();

    const close = document.querySelector("[data-image-preview-close]")!;
    fireEvent.pointerDown(close, { button: 0 });
    fireEvent.mouseDown(close);
    fireEvent.pointerUp(close);
    fireEvent.click(close);
    await waitFor(() => expect(closing()).toBe(true));
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("关掉之后焦点回到点开它的那颗按钮 —— 点遮罩关掉时焦点已经掉到 body 上", async () => {
    const { opener } = await openFromDialog();
    act(() => (document.activeElement as HTMLElement | null)?.blur());
    expect(document.activeElement).toBe(document.body);
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });
});

describe("灯箱压在页面上的别的层上面", () => {
  it("window 上听 Esc 的那一层(画板面板、工作流检查器)在灯箱开着时收不到这一下", async () => {
    const pageEsc = vi.fn();
    const listener = (event: KeyboardEvent) => event.key === "Escape" && pageEsc();
    window.addEventListener("keydown", listener);
    try {
      render(
        <ImagePreviewProvider>
          <Opener />
        </ImagePreviewProvider>,
      );
      fireEvent.click(screen.getByRole("button", { name: "看大图" }));
      await waitFor(() => expect(portal()).not.toBeNull());
      fireEvent.keyDown(window, { key: "Escape" });
      await waitFor(() => expect(closing()).toBe(true));
      expect(pageEsc).not.toHaveBeenCalled();

      //: 灯箱关了,Esc 照常归页面。
      fireEvent.keyDown(window, { key: "Escape" });
      expect(pageEsc).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener("keydown", listener);
    }
  });
});

describe("手写 DOM 的界面也走同一个灯箱", () => {
  it("从元素上派发的请求冒泡到 Provider,带着画廊打开", async () => {
    render(
      <ImagePreviewProvider>
        <div data-testid="host" />
      </ImagePreviewProvider>,
    );
    act(() => requestImagePreview(screen.getByTestId("host"), { ...gallery[0], gallery }));
    await waitFor(() => expect(portal()).not.toBeNull());
    expect(portal()?.textContent).toContain("1 / 2");
    expect(portal()?.textContent).toContain("第一张");
  });
});
