/** @vitest-environment jsdom */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { usePersistentTab } from "@/lib/usePersistentTab";

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
    window.localStorage.setItem("openstudio:tab:x", "删掉的tab");
    expect(renderHook(() => usePersistentTab("x", "media", ["media"] as const)).result.current[0]).toBe("media");
  });

  it("两个不同的 key 互不干扰", () => {
    const a = renderHook(() => usePersistentTab("a", "one", ["one", "two"] as const));
    act(() => a.result.current[1]("two"));
    expect(renderHook(() => usePersistentTab("b", "one", ["one", "two"] as const)).result.current[0]).toBe("one");
  });
});
