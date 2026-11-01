/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@tiptap/pm/state", () => ({
  TextSelection: { create: vi.fn((_doc: unknown, from: number, to: number) => ({ from, to })) },
}));

import { holdComposition, releaseComposition } from "./compositionObserver";

function viewWith(dom: HTMLElement) {
  const calls: string[] = [];
  const observer = {
    flush: vi.fn(() => calls.push("flush")),
    forceFlush: vi.fn(() => calls.push("forceFlush")),
    stop: vi.fn(() => calls.push("stop")),
    start: vi.fn(() => calls.push("start")),
  };
  return { view: { dom, domObserver: observer } as never, observer, calls };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("组词观察保护", () => {
  it("组词开始先读完已排队的变更再停观察", () => {
    const { view, observer, calls } = viewWith(document.createElement("div"));
    holdComposition(view);
    expect(calls).toEqual(["flush", "forceFlush", "stop"]);
    expect(observer.stop).toHaveBeenCalledOnce();
  });

  it("重复的组词开始事件不会重复停观察", () => {
    const { view, observer } = viewWith(document.createElement("div"));
    holdComposition(view);
    holdComposition(view);
    expect(observer.stop).toHaveBeenCalledOnce();
  });

  it("组词结束下一拍恢复观察并冲刷最终 DOM", () => {
    vi.useFakeTimers();
    const { view, observer } = viewWith(document.createElement("div"));
    holdComposition(view);

    releaseComposition(view);
    expect(observer.start).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(observer.start).toHaveBeenCalledOnce();
    expect(observer.flush).toHaveBeenCalledTimes(2);
  });

  it("没有组词开始时，结束事件不动观察", () => {
    vi.useFakeTimers();
    const { view, observer } = viewWith(document.createElement("div"));
    releaseComposition(view);
    vi.runAllTimers();
    expect(observer.start).not.toHaveBeenCalled();
  });

  it("组词结束后按 DOM 光标恢复选区，不把光标留在组出来的字前面", () => {
    vi.useFakeTimers();
    const dom = document.createElement("div");
    const paragraph = document.createElement("p");
    const text = document.createTextNode("你好");
    paragraph.append(text);
    dom.append(paragraph);

    const tr = { setSelection: vi.fn(), setMeta: vi.fn() };
    tr.setSelection.mockReturnValue(tr);
    tr.setMeta.mockReturnValue(tr);
    const view = {
      dom,
      domObserver: { flush: vi.fn(), forceFlush: vi.fn(), stop: vi.fn(), start: vi.fn() },
      isDestroyed: false,
      state: { doc: {}, selection: { eq: vi.fn(() => false) }, tr },
      posAtDOM: vi.fn((_node: Node, offset: number) => offset),
      dispatch: vi.fn(),
    };

    vi.spyOn(document, "getSelection").mockReturnValue({
      anchorNode: text, anchorOffset: 2, focusNode: text, focusOffset: 2,
    } as unknown as Selection);

    holdComposition(view as never);
    releaseComposition(view as never);
    vi.runAllTimers();

    expect(view.posAtDOM).toHaveBeenCalledWith(text, 2);
    expect(tr.setSelection).toHaveBeenCalledWith({ from: 2, to: 2 });
    expect(view.dispatch).toHaveBeenCalledOnce();
  });

  it("已有正文时清掉组词期间粘住的占位符空态类", () => {
    vi.useFakeTimers();
    const dom = document.createElement("div");
    const paragraph = document.createElement("p");
    paragraph.className = "is-empty is-editor-empty";
    paragraph.textContent = "你";
    dom.append(paragraph);

    const { view } = viewWith(dom);
    holdComposition(view);
    releaseComposition(view);
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

    const { view } = viewWith(dom);
    holdComposition(view);
    releaseComposition(view);
    vi.runAllTimers();

    expect(paragraph.classList.contains("is-empty")).toBe(true);
  });
});
