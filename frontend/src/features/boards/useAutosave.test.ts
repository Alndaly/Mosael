/** @vitest-environment jsdom */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAutosave } from "@/features/boards/useAutosave";

describe("useAutosave", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("值稳定下来之后才发一次", () => {
    const save = vi.fn();
    const { rerender } = renderHook(({ value }) => useAutosave(value, save, 500), {
      initialProps: { value: "载入的那份" as string | null },
    });

    rerender({ value: "改了一次" });
    rerender({ value: "又改了一次" });
    expect(save).not.toHaveBeenCalled();

    act(() => void vi.advanceTimersByTime(500));
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("又改了一次");
  });

  it("刚加载进来的那一份不回写", () => {
    // 不拦的话,每次打开画板都会立刻存一次 —— 服务端多一次无谓的写,而 updated_at 变了
    // 会让「最近编辑」乱掉:用户只是看了一眼,那张板就跳到最前面。
    const save = vi.fn();
    const { rerender } = renderHook(({ value }) => useAutosave(value, save, 500), {
      initialProps: { value: null as string | null },
    });
    rerender({ value: "服务端那份" });

    act(() => void vi.advanceTimersByTime(2000));
    expect(save).not.toHaveBeenCalled();
  });

  it("值没变就不发", () => {
    const save = vi.fn();
    const { rerender } = renderHook(({ value }) => useAutosave(value, save, 500), {
      initialProps: { value: "a" as string | null },
    });
    rerender({ value: "a" });
    act(() => void vi.advanceTimersByTime(2000));
    expect(save).not.toHaveBeenCalled();
  });

  it("卸载时把欠着的那次补上", () => {
    // 用户拖完最后一下就切走,防抖窗口还没到 —— 不补的话那一下就丢了。
    const save = vi.fn();
    const { rerender, unmount } = renderHook(({ value }) => useAutosave(value, save, 500), {
      initialProps: { value: "载入的那份" as string | null },
    });
    rerender({ value: "最后一下" });
    unmount();

    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("最后一下");
  });

  it("存完之后再改同一个值还会再存", () => {
    // settled 只是"上次落定的那份";用户撤销回到旧值也是一次真实编辑。
    const save = vi.fn();
    const { rerender } = renderHook(({ value }) => useAutosave(value, save, 500), {
      initialProps: { value: "a" as string | null },
    });
    rerender({ value: "b" });
    act(() => void vi.advanceTimersByTime(500));
    rerender({ value: "a" });
    act(() => void vi.advanceTimersByTime(500));

    expect(save.mock.calls.map((call) => call[0])).toEqual(["b", "a"]);
  });

  it("pending 在攒着的时候为真,发出去之后为假", () => {
    const save = vi.fn();
    const { result, rerender } = renderHook(({ value }) => useAutosave(value, save, 500), {
      initialProps: { value: "a" as string | null },
    });
    expect(result.current.pending).toBe(false);

    rerender({ value: "b" });
    expect(result.current.pending).toBe(true);

    act(() => void vi.advanceTimersByTime(500));
    expect(result.current.pending).toBe(false);
  });
});
