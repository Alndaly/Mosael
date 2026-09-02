/** @vitest-environment jsdom */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { usePersistentSelection, usePersistentTab, usePersistentViewport } from "@/lib/usePersistentTab";

/**
 * 「切走再回来,选择还在」。
 *
 * 用户报的是:改完东西回到剪辑页,左右两栏的 tab 都重置了 —— 他刚刚选的「字幕」变回「素材」。
 * 那是因为 tab 活在组件 `useState` 里,而组件在导航时会卸载。这类状态不是"这一刻的临时值",
 * 是**这个人怎么用这个工具**的一部分。
 *
 * 这个钩子本来就在(工作流的连线样式、AI 工作台的 tab 都用它),剪辑页两处没用上而已。
 * 补这份用例是因为它此前一条都没有 —— 一个"跨导航还在"的承诺,值得有人守着。
 */
describe("会活过导航的 tab", () => {
  beforeEach(() => window.localStorage.clear());

  it("重新挂载后还是上次那个", () => {
    const first = renderHook(() => usePersistentTab("x", "media", ["media", "subtitle"] as const));
    act(() => first.result.current[1]("subtitle"));
    first.unmount();

    expect(renderHook(() => usePersistentTab("x", "media", ["media", "subtitle"] as const)).result.current[0])
      .toBe("subtitle");
  });

  it("没存过就用默认", () => {
    expect(renderHook(() => usePersistentTab("x", "media", ["media"] as const)).result.current[0]).toBe("media");
  });

  it("存着一个已经不存在的 tab 时回落 —— 别把人卡在一个删掉的页面上", () => {
    window.localStorage.setItem("mosael:tab:x", "删掉的tab");
    expect(renderHook(() => usePersistentTab("x", "media", ["media"] as const)).result.current[0]).toBe("media");
  });

  it("两个不同的 key 互不干扰", () => {
    const a = renderHook(() => usePersistentTab("a", "one", ["one", "two"] as const));
    act(() => a.result.current[1]("two"));
    expect(renderHook(() => usePersistentTab("b", "one", ["one", "two"] as const)).result.current[0]).toBe("one");
  });
});

describe("会活过导航的选中", () => {
  beforeEach(() => window.localStorage.clear());

  it("重新挂载后还选着那一个", () => {
    const first = renderHook(() => usePersistentSelection("w", ["a", "b"]));
    act(() => first.result.current[1]("b"));
    first.unmount();

    expect(renderHook(() => usePersistentSelection("w", ["a", "b"])).result.current[0]).toBe("b");
  });

  it("选中的东西被删掉了就当没选过 —— 而不是指着一个不存在的 id", () => {
    window.localStorage.setItem("mosael:selected:w", "已经删了");
    expect(renderHook(() => usePersistentSelection("w", ["a", "b"])).result.current[0]).toBeNull();
  });

  it("列表还没加载出来时不清空,并显式标记正在恢复", () => {
    window.localStorage.setItem("mosael:selected:w", "a");
    const loading = renderHook(() => usePersistentSelection("w", undefined));
    expect(loading.result.current[0]).toBe("a");
    expect(loading.result.current[2].restoring).toBe(true);
  });

  it("列表已经加载且为空时判为无效 —— 空数组不是加载中", () => {
    window.localStorage.setItem("mosael:selected:w", "a");
    const empty = renderHook(() => usePersistentSelection("w", []));
    expect(empty.result.current[0]).toBeNull();
    expect(empty.result.current[2].restoring).toBe(false);
  });

  it("清空选择也要落地 —— 否则刷新之后它又回来了", () => {
    const hook = renderHook(() => usePersistentSelection("w", ["a"]));
    act(() => hook.result.current[1]("a"));
    act(() => hook.result.current[1](null));
    hook.unmount();

    expect(renderHook(() => usePersistentSelection("w", ["a"])).result.current[0]).toBeNull();
  });
});

/**
 * 「上次停在哪儿,回来还在哪儿」。
 *
 * 用户报的是:每次刷新或重新进入工作流详情,画布都 fitView 把所有节点框回视野 —— 图一大,
 * 他每次回来都要重新找到刚才在看的那一块,而**离开时的位置本来就是最有价值的信息**。
 */
describe("usePersistentViewport", () => {
  beforeEach(() => localStorage.clear());

  it("第一次进来没有存过 —— 调用方据此决定要不要 fitView", () => {
    expect(renderHook(() => usePersistentViewport("wf-1")).result.current.saved).toBeNull();
  });

  it("记住之后再挂载就回到那个位置", () => {
    const first = renderHook(() => usePersistentViewport("wf-1"));
    act(() => first.result.current.remember({ x: -120, y: 40, zoom: 0.75 }));
    expect(renderHook(() => usePersistentViewport("wf-1")).result.current.saved).toEqual({
      x: -120,
      y: 40,
      zoom: 0.75,
    });
  });

  it("每张图各记各的 —— 换一张不该继承上一张停在哪儿", () => {
    const a = renderHook(() => usePersistentViewport("wf-a"));
    act(() => a.result.current.remember({ x: 1, y: 2, zoom: 1.5 }));
    expect(renderHook(() => usePersistentViewport("wf-b")).result.current.saved).toBeNull();
  });

  it("挂载后不再跟着 storage 变", () => {
    // 读成响应式的话,自己保存又会触发自己重定位 —— 用户拖动时画布会和自己打架。
    const { result } = renderHook(() => usePersistentViewport("wf-1"));
    act(() => result.current.remember({ x: 9, y: 9, zoom: 2 }));
    expect(result.current.saved).toBeNull();
  });

  describe("坏数据一律当没存过", () => {
    it.each([
      ["不是 JSON", "{{{"],
      ["缺字段", '{"x":1,"y":2}'],
      ["不是数字", '{"x":null,"y":2,"zoom":1}'],
      // zoom 为 0 / 负数会让画布彻底不可用,而这种值只可能来自坏数据。
      ["zoom 为 0", '{"x":1,"y":2,"zoom":0}'],
      ["zoom 为负", '{"x":1,"y":2,"zoom":-1}'],
    ])("%s", (_name, raw) => {
      localStorage.setItem("mosael:viewport:wf-1", raw);
      expect(renderHook(() => usePersistentViewport("wf-1")).result.current.saved).toBeNull();
    });
  });
});
