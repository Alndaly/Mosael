/** @vitest-environment jsdom */
/**
 * 「报错以后圈还在转」是这一段最容易漏的地方:只在开头 setTrue、指望面板自己消失的话,
 * 一旦失败面板还在,那个圈就永远转下去 —— 用户既不知道失败了,也再点不动第二次。
 */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useSubmitting } from "./useSubmitting";

describe("提交中", () => {
  it("点下去立刻转,落地了才停", async () => {
    const { result } = renderHook(() => useSubmitting());
    let settle: () => void = () => {};
    act(() => result.current.run(() => new Promise<void>((resolve) => (settle = resolve))));
    expect(result.current.submitting).toBe(true);
    await act(async () => {
      settle();
    });
    expect(result.current.submitting).toBe(false);
  });

  it("**失败也要停** —— 否则那个圈会一直转下去", async () => {
    const { result } = renderHook(() => useSubmitting());
    await act(async () => {
      result.current.run(() => Promise.reject(new Error("挂了")));
    });
    expect(result.current.submitting).toBe(false);
  });

  it("同步抛出来的也一样", () => {
    const { result } = renderHook(() => useSubmitting());
    act(() => {
      result.current.run(() => {
        throw new Error("当场就挂");
      });
    });
    expect(result.current.submitting).toBe(false);
  });

  it("不返回 Promise 的回调:跑完就停,不会卡住", async () => {
    const { result } = renderHook(() => useSubmitting());
    await act(async () => {
      result.current.run(() => undefined);
    });
    expect(result.current.submitting).toBe(false);
  });
});
