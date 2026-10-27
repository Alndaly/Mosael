/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";

import { pauseCompositionObserver, resumeCompositionObserver } from "./compositionObserver";

function viewWith(dom: HTMLElement) {
  const observer = { stop: vi.fn(), start: vi.fn(), flush: vi.fn() };
  return { view: { dom, domObserver: observer } as never, observer };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("组词观察保护", () => {
  it("组词开始停观察，结束恢复并冲刷最终 DOM", () => {
    vi.useFakeTimers();
    const dom = document.createElement("div");
    const { view, observer } = viewWith(dom);

    expect(pauseCompositionObserver(view)).toBe(false);
    expect(observer.stop).toHaveBeenCalledOnce();

    expect(resumeCompositionObserver(view)).toBe(false);
    expect(observer.start).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(observer.start).toHaveBeenCalledOnce();
    expect(observer.flush).toHaveBeenCalledOnce();
  });

  it("已有正文时清掉组词期间粘住的占位符空态类", () => {
    vi.useFakeTimers();
    const dom = document.createElement("div");
    const paragraph = document.createElement("p");
    paragraph.className = "is-empty is-editor-empty";
    paragraph.textContent = "你";
    dom.append(paragraph);

    resumeCompositionObserver(viewWith(dom).view);
    vi.runAllTimers();

    expect(paragraph.classList.contains("is-empty")).toBe(false);
    expect(paragraph.classList.contains("is-editor-empty")).toBe(false);
  });

  it("正文仍为空时保留占位符", () => {
    vi.useFakeTimers();
    const dom = document.createElement("div");
    const paragraph = document.createElement("p");
    paragraph.className = "is-empty is-editor-empty";
    dom.append(paragraph);

    resumeCompositionObserver(viewWith(dom).view);
    vi.runAllTimers();

    expect(paragraph.classList.contains("is-empty")).toBe(true);
  });
});
