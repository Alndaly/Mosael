/** @vitest-environment jsdom */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useEditorPanels } from "./useEditorPanels";

/**
 * 面板宽度有两条进入路径,它们的兜底规则**不一样**:
 *
 * - 读盘时值可能缺失或是垃圾 → 落到 fallback(默认宽);
 * - 拖动时值一定是个数 → 只夹进 [min, max]。
 *
 * 这两条曾经被合成一个 `Number(v) || fallback` 的函数。那样写,把右栏一路拖到宽度恰好为 0
 * 会撞进 `|| fallback`,栏位不是收到最小值而是弹回默认宽 —— 拖得越狠反而越宽。
 */

const KEY = "mosael.editor.panels.v2";

function drag(hook: { current: ReturnType<typeof useEditorPanels> }, which: "left" | "right" | "timeline", dx: number, dy = 0) {
  act(() => {
    hook.current.startDrag(which)({
      preventDefault() {},
      clientX: 500,
      clientY: 500,
    } as unknown as React.PointerEvent);
  });
  act(() => {
    window.dispatchEvent(new MouseEvent("pointermove", { clientX: 500 + dx, clientY: 500 + dy }));
  });
  act(() => {
    window.dispatchEvent(new MouseEvent("pointerup"));
  });
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("拖动只夹范围,不兜底", () => {
  it("右栏拖到宽度恰好为 0,收到最小值而不是默认宽", () => {
    const { result } = renderHook(() => useEditorPanels());
    const start = result.current.sizes.right; // 264
    drag(result, "right", start); // origin.right - dx === 0
    expect(result.current.sizes.right).toBe(200);
  });

  it("时间线同理", () => {
    const { result } = renderHook(() => useEditorPanels());
    const start = result.current.sizes.timeline;
    drag(result, "timeline", 0, start);
    expect(result.current.sizes.timeline).toBe(160);
  });

  it("拖过头夹在上界", () => {
    const { result } = renderHook(() => useEditorPanels());
    drag(result, "right", -9999);
    expect(result.current.sizes.right).toBe(480);
  });
});

describe("读盘才兜底", () => {
  it("存坏了不影响其他栏 —— 每一项各自兜底", () => {
    window.localStorage.setItem(KEY, JSON.stringify({ left: { media: "垃圾" }, right: 300, timeline: 400 }));
    const { result } = renderHook(() => useEditorPanels());
    expect(result.current.sizes.left.media).toBe(252); // 兜底
    expect(result.current.sizes.right).toBe(300); // 保住
    expect(result.current.sizes.timeline).toBe(400);
  });

  it("整个 JSON 都坏了也能起来", () => {
    window.localStorage.setItem(KEY, "{不是 json");
    const { result } = renderHook(() => useEditorPanels());
    expect(result.current.sizes.right).toBe(264);
  });

  it("存的值超范围要夹回去", () => {
    window.localStorage.setItem(KEY, JSON.stringify({ right: 99999 }));
    const { result } = renderHook(() => useEditorPanels());
    expect(result.current.sizes.right).toBe(480);
  });
});

describe("宽度落盘", () => {
  it("拖完写回 localStorage", () => {
    const { result } = renderHook(() => useEditorPanels());
    drag(result, "right", -50);
    expect(JSON.parse(window.localStorage.getItem(KEY)!).right).toBe(314);
  });

  it("左栏宽度按页签分别记忆 —— 素材栏窄,逐字稿栏宽", () => {
    const { result } = renderHook(() => useEditorPanels());
    expect(result.current.sizes.left.media).toBe(252);
    expect(result.current.sizes.left.transcript).toBe(420);
  });
});

describe("紧凑断点", () => {
  it("窄窗口下左栏最宽 300 —— 否则三栏挤成一团", () => {
    const { result } = renderHook(() => useEditorPanels());
    // 默认 media 栏 252,已经小于 300,收不收都一样;换到 transcript(420)才看得出来。
    act(() => result.current.setTab("transcript"));
    expect(result.current.leftWidth).toBe(result.current.compact ? 300 : 420);
  });
});
