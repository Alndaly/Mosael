/** @vitest-environment jsdom */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { installSaveShortcut, useSaveShortcut } from "./saveShortcut";

/**
 * ⌘S 全应用一个行为:能存就存,不能存也不让浏览器弹「存储网页」。此前只有工作流画布认它,而且焦点在
 * 检查器字段里时也让路;笔记、画板、3D 场景里按下去,网页版弹的是浏览器的另存为。
 */
let uninstall: () => void = () => undefined;
beforeEach(() => {
  uninstall = installSaveShortcut(window);
});
afterEach(() => {
  uninstall();
  document.body.innerHTML = "";
});

function press(target: EventTarget, init: KeyboardEventInit) {
  const event = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init });
  act(() => void target.dispatchEvent(event));
  return event;
}

describe("⌘S / Ctrl+S", () => {
  it("没有页面登记时也拦下(不弹浏览器的「存储网页」)", () => {
    expect(press(document.body, { key: "s", code: "KeyS", metaKey: true }).defaultPrevented).toBe(true);
    expect(press(document.body, { key: "s", code: "KeyS", ctrlKey: true }).defaultPrevented).toBe(true);
  });

  it("焦点在输入框 / 可编辑区里一样接:存的是这一页", () => {
    const save = vi.fn();
    renderHook(() => useSaveShortcut(save));
    const input = document.body.appendChild(document.createElement("textarea"));
    const editable = document.body.appendChild(document.createElement("div"));
    editable.contentEditable = "true";
    expect(press(input, { key: "s", code: "KeyS", metaKey: true }).defaultPrevented).toBe(true);
    expect(press(editable, { key: "s", code: "KeyS", ctrlKey: true }).defaultPrevented).toBe(true);
    expect(save).toHaveBeenCalledTimes(2);
  });

  it("后登记的先接;它卸下之后回到底下那一层", () => {
    const below = vi.fn();
    const above = vi.fn();
    renderHook(() => useSaveShortcut(below));
    const top = renderHook(() => useSaveShortcut(above));
    press(document.body, { key: "s", code: "KeyS", metaKey: true });
    expect(above).toHaveBeenCalledTimes(1);
    expect(below).not.toHaveBeenCalled();
    top.unmount();
    press(document.body, { key: "s", code: "KeyS", metaKey: true });
    expect(below).toHaveBeenCalledTimes(1);
  });

  it("调的是最新那次渲染给的函数(页面每次渲染都给一个新的)", () => {
    const first = vi.fn();
    const second = vi.fn();
    const view = renderHook(({ save }) => useSaveShortcut(save), { initialProps: { save: first } });
    view.rerender({ save: second });
    press(document.body, { key: "s", code: "KeyS", metaKey: true });
    expect(second).toHaveBeenCalledTimes(1);
    expect(first).not.toHaveBeenCalled();
  });

  it("⇧⌘S、⌥⌘S、单按 S 都不是它", () => {
    const save = vi.fn();
    renderHook(() => useSaveShortcut(save));
    expect(press(document.body, { key: "S", code: "KeyS", metaKey: true, shiftKey: true }).defaultPrevented).toBe(false);
    expect(press(document.body, { key: "ß", code: "KeyS", metaKey: true, altKey: true }).defaultPrevented).toBe(false);
    expect(press(document.body, { key: "s", code: "KeyS" }).defaultPrevented).toBe(false);
    expect(save).not.toHaveBeenCalled();
  });

  it("重复装(热更新)不叠第二个监听:按一次只存一次", () => {
    const again = installSaveShortcut(window);
    const save = vi.fn();
    renderHook(() => useSaveShortcut(save));
    press(document.body, { key: "s", code: "KeyS", metaKey: true });
    expect(save).toHaveBeenCalledTimes(1);
    expect(again).toBe(uninstall);
  });
});
