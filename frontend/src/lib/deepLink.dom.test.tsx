/** @vitest-environment jsdom */
import { act, render } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import { emitOpenEvent, useOpenRequest } from "@/lib/deepLink";

/**
 * 「打开某一条」的请求放进信箱,不再按 80 / 300 / 800ms 连发三次去赌对方什么时候准备好。
 *
 * 连发的两个毛病都真实发生过:慢一点的机器上三次都赶不上,请求就丢了;页面早卸掉之后定时器
 * 照样触发 —— CI 上测试结束、jsdom 拆掉,800ms 那一发撞上一个不存在的 window,整轮测试红了。
 */

function Receiver({ event, ready = true, onOpen }: { event: string; ready?: boolean; onOpen: (id: string) => void }) {
  useOpenRequest(event, (id) => {
    if (!ready) return false;
    onOpen(id);
  }, [ready]);
  return null;
}

describe("打开请求的信箱", () => {
  it("页面还没挂载时发的请求不丢 —— 挂载时自己来取", () => {
    emitOpenEvent("test:open-a", "r1");
    const opened = vi.fn();
    render(<Receiver event="test:open-a" onOpen={opened} />);
    expect(opened).toHaveBeenCalledWith("r1");
  });

  it("已经挂着的页面当场收到", () => {
    const opened = vi.fn();
    render(<Receiver event="test:open-b" onOpen={opened} />);
    act(() => emitOpenEvent("test:open-b", "r2"));
    expect(opened).toHaveBeenCalledWith("r2");
  });

  it("接不住(那一条还没加载出来)就先留着,准备好了再投", () => {
    const opened = vi.fn();
    const view = render(<Receiver event="test:open-c" ready={false} onOpen={opened} />);
    act(() => emitOpenEvent("test:open-c", "r3"));
    expect(opened).not.toHaveBeenCalled();
    view.rerender(<Receiver event="test:open-c" ready onOpen={opened} />);
    expect(opened).toHaveBeenCalledWith("r3");
  });

  it("收下就拿走 —— 下次再进这一页不会又打开同一条", () => {
    emitOpenEvent("test:open-d", "r4");
    const first = vi.fn();
    render(<Receiver event="test:open-d" onOpen={first} />).unmount();
    const second = vi.fn();
    render(<Receiver event="test:open-d" onOpen={second} />);
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).not.toHaveBeenCalled();
  });

  it("不留任何定时器 —— 页面拆掉之后没有东西会再去碰 window", () => {
    vi.useFakeTimers();
    try {
      emitOpenEvent("test:open-e", "r5");
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
