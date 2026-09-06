/** @vitest-environment jsdom */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useCanvasPosture } from "@/features/workflows/useCanvasPosture";

/**
 * 这里钉的是一件**不该存在**的事:视口每动一帧就 setState 一次。
 *
 * 曾经有个 `tick` 给"按节点屏幕位置摆放的贴靠面板"用。那个面板后来改成了 React Flow 的
 * `<Panel position="bottom-right">`,靠 CSS 定位,而 tick 留了下来 —— 没有任何地方再读它,
 * 却仍然在平移/缩放时每帧 setState,于是整个编辑器(带就绪度分析等几个重 memo)每帧重渲染。
 *
 * 死状态本身不显眼,它的代价是持续的、看不见的。所以钉住:这个 hook 只在**两个离散时刻**
 * 变(就绪、平移起止),不存在每帧回调。
 */
describe("画布姿态", () => {
  it("只有两个离散时刻会改状态", () => {
    const { result } = renderHook(() => useCanvasPosture());
    expect(Object.keys(result.current.handlers).sort()).toEqual(["onInit", "onMoveEnd", "onMoveStart"]);
    expect(result.current).not.toHaveProperty("tick");

    expect(result.current.ready).toBe(false);
    act(() => result.current.handlers.onInit());
    expect(result.current.ready).toBe(true);

    act(() => result.current.handlers.onMoveStart());
    expect(result.current.panning).toBe(true);
    act(() => result.current.handlers.onMoveEnd());
    expect(result.current.panning).toBe(false);
  });

  it("回调组引用稳定", () => {
    // 不稳的话它会进别人的依赖数组,反过来又造成一轮重渲染。
    const { result, rerender } = renderHook(() => useCanvasPosture());
    const first = result.current.handlers;
    rerender();
    expect(result.current.handlers).toBe(first);
  });
});
