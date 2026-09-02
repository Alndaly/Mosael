/** @vitest-environment jsdom */
import React from "react";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAutosave } from "@/features/boards/useAutosave";

function deferred() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

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
    // confirmedValue 只是"上次落定的那份";用户撤销回到旧值也是一次真实编辑。
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

  it("服务端真正确认后才把这份内容视为已保存", async () => {
    const first = deferred();
    const save = vi.fn(() => first.promise);
    const { result, rerender } = renderHook(({ value }) => useAutosave(value, save, 500), {
      initialProps: { value: "a" as string | null },
    });

    rerender({ value: "b" });
    act(() => void vi.advanceTimersByTime(500));

    expect(save).toHaveBeenCalledWith("b");
    expect(result.current.pending).toBe(true);

    await act(async () => first.resolve());
    expect(result.current.pending).toBe(false);
  });

  it("一次只存一份,飞行期间的连续编辑只追存最新值", async () => {
    const first = deferred();
    const latest = deferred();
    const save = vi.fn()
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => latest.promise);
    const { result, rerender } = renderHook(({ value }) => useAutosave(value, save, 500), {
      initialProps: { value: "a" as string | null },
    });

    rerender({ value: "b" });
    act(() => void vi.advanceTimersByTime(500));
    rerender({ value: "c" });
    rerender({ value: "d" });

    expect(save.mock.calls.map((call) => call[0])).toEqual(["b"]);

    await act(async () => first.resolve());
    expect(save.mock.calls.map((call) => call[0])).toEqual(["b", "d"]);
    expect(result.current.pending).toBe(true);

    await act(async () => latest.resolve());
    expect(result.current.pending).toBe(false);
  });

  it("失败的保存会继续标记为待落库", async () => {
    const save = vi.fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(undefined);
    const { result, rerender } = renderHook(({ value }) => useAutosave(value, save, 500), {
      initialProps: { value: "a" as string | null },
    });

    rerender({ value: "b" });
    act(() => void vi.advanceTimersByTime(500));
    await act(async () => undefined);
    expect(result.current.pending).toBe(true);

    // 先回到确实已保存的 a,再重做 b。如果失败的 b 被当成 confirmedValue,
    // 第二次 b 就会被错误地跳过。
    rerender({ value: "a" });
    rerender({ value: "b" });
    act(() => void vi.advanceTimersByTime(500));
    await act(async () => undefined);

    expect(save.mock.calls.map((call) => call[0])).toEqual(["b", "b"]);
  });

  it("在 StrictMode 重新执行 effect 后仍能回报保存完成", async () => {
    const saving = deferred();
    const { result, rerender } = renderHook(({ value }) => useAutosave(value, () => saving.promise, 500), {
      initialProps: { value: "a" as string | null },
      wrapper: React.StrictMode,
    });

    rerender({ value: "b" });
    act(() => void vi.advanceTimersByTime(500));
    expect(result.current.pending).toBe(true);

    await act(async () => saving.resolve());
    expect(result.current.pending).toBe(false);
  });

  it("卸载时有一份正在保存,也会在它结束后追存最后的编辑", async () => {
    const first = deferred();
    const save = vi.fn()
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValueOnce(undefined);
    const { rerender, unmount } = renderHook(({ value }) => useAutosave(value, save, 500), {
      initialProps: { value: "a" as string | null },
    });

    rerender({ value: "b" });
    act(() => void vi.advanceTimersByTime(500));
    rerender({ value: "c" });
    unmount();

    await act(async () => first.resolve());
    expect(save.mock.calls.map((call) => call[0])).toEqual(["b", "c"]);
  });
});
