/** @vitest-environment jsdom */

/**
 * 提示条让开贴底的输入区。维护者截图:AI Studio 里「语音合成 · 已完成」盖在输入框右下角的发送键和「⌘Enter 生成」上。
 *
 * 触发条件是**挡掉那一列的大半**(见 toastClearance 的模块说明):只压到一角不抬 ——
 * 真机:AI Studio 创作页输入卡右缘只压进那一列 64px(18%),抬起来会让提示条飘到输入框上方。
 */
import React from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TOAST_EDGE, toastBottomOffset, useToastClearance } from "./toastClearance";
import { resetNativeViewForTests } from "@/lib/nativeView";

const VIEWPORT = { width: 1440, height: 900 };
const box = (left: number, top: number, right: number, bottom: number) => ({ left, top, right, bottom, width: right - left, height: bottom - top });

describe("toastBottomOffset", () => {
  it("没有挂标记的输入区:待在默认的边距上", () => {
    expect(toastBottomOffset([], VIEWPORT)).toBe(TOAST_EDGE);
  });

  it("输入卡只压到那一列一角(18%):不抬 —— 提示条待在右下角", () => {
    // 真机:AI Studio 创作页输入卡,右缘 1124 压进那一列(1060–1416)64px。
    expect(toastBottomOffset([box(480, 744, 1124, 886)], VIEWPORT)).toBe(TOAST_EDGE);
  });

  it("输入卡挡掉大半(挡住整个发送键那一片):抬到它上沿之上,留 12px", () => {
    expect(toastBottomOffset([box(900, 744, 1400, 886)], VIEWPORT)).toBe(900 - 744 + 12);
  });

  it("输入区不在那一列(窗口宽、输入框在左半边):不动", () => {
    expect(toastBottomOffset([box(240, 744, 1000, 886)], VIEWPORT)).toBe(TOAST_EDGE);
  });

  it("输入区在提示条上面(没贴底):不动", () => {
    expect(toastBottomOffset([box(1000, 300, 1400, 600)], VIEWPORT)).toBe(TOAST_EDGE);
  });

  it("藏着的(量出来是 0×0)不算", () => {
    expect(toastBottomOffset([box(1200, 900, 1200, 900)], VIEWPORT)).toBe(TOAST_EDGE);
  });

  it("几处都挡着:按最高的那一处抬", () => {
    expect(toastBottomOffset([box(900, 744, 1400, 886), box(1100, 700, 1430, 890)], VIEWPORT)).toBe(900 - 700 + 12);
  });

  it("输入区长得很高也不把提示条顶出窗口", () => {
    expect(toastBottomOffset([box(1000, 20, 1430, 890)], VIEWPORT)).toBe(900 - 120);
  });
});

function Probe() {
  return <output data-testid="offset">{useToastClearance()}</output>;
}

describe("useToastClearance", () => {
  let rect = box(900, 744, 1400, 886);
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      return (this.hasAttribute("data-toast-avoid") ? rect : box(0, 0, 0, 0)) as DOMRect;
    });
    Object.assign(window, { innerWidth: VIEWPORT.width, innerHeight: VIEWPORT.height });
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  const settle = () => act(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
  const offset = () => Number(screen.getByTestId("offset").textContent);

  it("输入区挂上来就抬、拿掉就回去;窗口一变重新量", async () => {
    function Page({ composer }: { composer: boolean }) {
      return (
        <>
          <Probe />
          {composer && <form data-toast-avoid="" />}
        </>
      );
    }
    const view = render(<Page composer={false} />);
    await settle();
    expect(offset()).toBe(TOAST_EDGE);

    rect = box(900, 744, 1400, 886);
    view.rerender(<Page composer />);
    await settle();
    await settle();
    expect(offset(), "挡掉大半:抬起来").toBe(900 - 744 + 12);

    rect = box(240, 744, 1000, 886);
    act(() => void window.dispatchEvent(new Event("resize")));
    await settle();
    expect(offset()).toBe(TOAST_EDGE);

    rect = box(900, 744, 1400, 886);
    view.rerender(<Page composer={false} />);
    await settle();
    await settle();
    expect(offset()).toBe(TOAST_EDGE);
  });
  //: ADR 0051:原生视图(内嵌浏览器、工作台)在前台时提示条画在它上面,页面整块在它底下 —— 底下那页看不见的输入框不该把提示条
  //: 抬起来;外壳里的(工作台右边那一列的智能体输入框)照样让。
  it("原生视图在前台时只认外壳里的输入区", async () => {
    let push: ((state: { visible: boolean }) => void) | null = null;
    vi.stubGlobal("mosaelPublish", {
      onViewState: (callback: (state: { visible: boolean }) => void) => {
        push = callback;
        return () => (push = null);
      },
    });
    resetNativeViewForTests();
    try {
      function Page({ inChrome }: { inChrome: boolean }) {
        return (
          <>
            <Probe />
            {inChrome ? (
              <aside data-app-chrome="">
                <form data-toast-avoid="" />
              </aside>
            ) : (
              <form data-toast-avoid="" />
            )}
          </>
        );
      }
      const view = render(<Page inChrome={false} />);
      await settle();
      await settle();
      expect(offset(), "视图不在前台:照常让").toBe(900 - 744 + 12);

      act(() => push?.({ visible: true }));
      await settle();
      await settle();
      expect(offset(), "页面在网页底下:不让").toBe(TOAST_EDGE);

      view.rerender(<Page inChrome />);
      await settle();
      await settle();
      expect(offset(), "外壳里的:让").toBe(900 - 744 + 12);
    } finally {
      vi.unstubAllGlobals();
      resetNativeViewForTests();
    }
  });
});
