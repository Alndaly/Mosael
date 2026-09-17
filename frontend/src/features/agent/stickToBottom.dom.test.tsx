/** @vitest-environment jsdom */
/**
 * 贴底跟随:钉住那条让它在 Windows 上失效的竞态。
 *
 * 上一版用「距底距离」判断要不要继续跟随。内容长高之后我们把 scrollTop 顶到底,而 scroll 事件
 * 要到**下一帧**才派发 —— 若这中间内容又长了一截,处理器读到的距底距离就超了阈值,跟随被关掉,
 * 而它只在用户手动滚回底部时才重开。渲染越慢、每帧长得越多越容易撞上。
 *
 * 所以第一条用例模拟的正是那一幕:**先长内容,再派发 scroll**,断言跟随没被关掉。
 * 这些用例驱动的是真的 hook —— 在测试里另写一份判据的话,改坏 hook 它照样绿。
 */
import React from "react";
import { render, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useStickToBottom } from "./stickToBottom";

/** jsdom 不做布局:scrollHeight / clientHeight 恒为 0,得自己接管。 */
function measurable(el: HTMLElement, clientHeight: number) {
  let scrollHeight = clientHeight;
  Object.defineProperty(el, "clientHeight", { configurable: true, get: () => clientHeight });
  Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => scrollHeight });
  // scrollTop 在 jsdom 里可写但不夹取,而真浏览器会夹到 [0, scrollHeight - clientHeight] ——
  // 不夹的话 `scrollTop = scrollHeight` 会留下一个真实浏览器里不可能出现的值。
  let top = 0;
  Object.defineProperty(el, "scrollTop", {
    configurable: true,
    get: () => top,
    set: (next: number) => {
      top = Math.max(0, Math.min(next, scrollHeight - clientHeight));
    },
  });
  return {
    grow(by: number) {
      scrollHeight += by;
    },
  };
}

function Harness({ onReady }: { onReady: (api: ReturnType<typeof useStickToBottom<HTMLDivElement>>) => void }) {
  const stick = useStickToBottom<HTMLDivElement>("session-1");
  React.useEffect(() => onReady(stick));
  return <div ref={stick.ref} data-testid="thread" />;
}

let ro: { observe: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> };

beforeEach(() => {
  ro = { observe: vi.fn(), disconnect: vi.fn() };
  vi.stubGlobal("ResizeObserver", class {
    observe = ro.observe;
    unobserve = vi.fn();
    disconnect = ro.disconnect;
  });
  Element.prototype.scrollTo = function scrollTo(this: Element, options?: ScrollToOptions | number) {
    if (typeof options === "object" && options?.top !== undefined) this.scrollTop = options.top;
  } as Element["scrollTo"];
});

afterEach(() => vi.unstubAllGlobals());

function mount() {
  let api!: ReturnType<typeof useStickToBottom<HTMLDivElement>>;
  const view = render(<Harness onReady={(next) => { api = next; }} />);
  const el = view.getByTestId("thread");
  const box = measurable(el, 600);
  return { el, box, get api() { return api; } };
}

/** 内容长高,并把 MutationObserver 会看到的那次变更真的做出来。 */
async function appendContent(el: HTMLElement, box: { grow(by: number): void }, px: number) {
  await act(async () => {
    box.grow(px);
    el.appendChild(document.createElement("p"));
    // MutationObserver 是微任务时机 —— 让它跑完。
    await Promise.resolve();
  });
}

const fireScroll = (el: HTMLElement) => act(() => { el.dispatchEvent(new Event("scroll")); });

describe("贴底跟随", () => {
  it("内容在 scroll 事件派发之前又长高,不该停掉跟随", async () => {
    const h = mount();
    const { el, box } = h;
    await appendContent(el, box, 400); // 跟随中 → scrollTop 被顶到底(1000-600=400)
    expect(el.scrollTop).toBe(400);

    // 关键一幕:下一帧到来之前模型又吐了 300px,此时距底 300 —— 老判据(< 140)在这里判定停跟随。
    box.grow(300);
    await fireScroll(el);
    expect(h.api.pinned).toBe(true);

    // 而且接着长内容时仍然跟得上。
    await appendContent(el, box, 100);
    expect(el.scrollTop).toBe(el.scrollHeight - 600);
  });

  it("用户往上滚就停下,并说明底下有新内容", async () => {
    const h = mount();
    const { el, box } = h;
    await appendContent(el, box, 400);

    el.scrollTop = 100; // 往上翻历史
    await fireScroll(el);
    expect(h.api.pinned).toBe(false);

    await appendContent(el, box, 300);
    expect(el.scrollTop).toBe(100); // 不被硬拽回底部
    expect(h.api.unseen).toBe(true);
  });

  it("滚回底部附近就自动恢复跟随", async () => {
    const h = mount();
    const { el, box } = h;
    await appendContent(el, box, 400);
    el.scrollTop = 100;
    await fireScroll(el);
    expect(h.api.pinned).toBe(false);

    el.scrollTop = el.scrollHeight - 600 - 20; // 距底 20px,在容差内
    await fireScroll(el);
    expect(h.api.pinned).toBe(true);
    expect(h.api.unseen).toBe(false);
  });

  it("触控板回弹那 1px 不算「往上看」", async () => {
    const h = mount();
    const { el, box } = h;
    await appendContent(el, box, 400);
    box.grow(300); // 拉开距底距离,排除"在底部所以恒真"
    el.scrollTop = 399;
    await fireScroll(el);
    expect(h.api.pinned).toBe(true);
  });

  it("scrollToBottom 把跟随重新打开", async () => {
    const h = mount();
    const { el, box } = h;
    await appendContent(el, box, 400);
    el.scrollTop = 0;
    await fireScroll(el);
    expect(h.api.pinned).toBe(false);

    await act(async () => h.api.scrollToBottom());
    expect(h.api.pinned).toBe(true);
    expect(el.scrollTop).toBe(el.scrollHeight - 600);
  });
});
