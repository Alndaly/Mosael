/**
 * Computer Use 的「被控制中」状态与急停(ADR 0075 安全 2/3)。
 *
 * 纯状态机,不碰 Electron:这里钉住的是语义 —— 一次动作点亮、闲置自动熄灭、急停**挡住之后
 * 所有动作**(不是「歇一会儿」)、恢复是用户明确要求的、状态变化推给显示层。
 */
import { describe, expect, it, vi } from "vitest";

// CommonJS is intentional: main.cjs loads this exact module.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createComputerUseGuard } = require("./computerUseGuard.cjs") as {
  createComputerUseGuard: (options?: {
    idleMs?: number;
    now?: () => number;
    onStateChange?: (state: { active: boolean; stopped: boolean; reason: string }) => void;
    setTimeout?: (fn: () => void, ms: number) => { unref?: () => void };
    clearTimeout?: (timer: { unref?: () => void }) => void;
  }) => {
    noteActivity: () => void;
    stop: (reason?: string) => boolean;
    resume: () => boolean;
    isActive: () => boolean;
    isStopped: () => boolean;
    state: () => { active: boolean; stopped: boolean };
    dispose: () => void;
  };
};

function guard() {
  const states: string[] = [];
  const timers: Array<{ fn: () => void; ms: number; unref: () => void }> = [];
  const instance = createComputerUseGuard({
    idleMs: 1000,
    now: () => 42,
    onStateChange: (state) => states.push(`${state.active ? "active" : "off"}:${state.stopped ? "stopped" : "open"}:${state.reason}`),
    setTimeout: (fn, ms) => {
      const timer = { fn, ms, unref: () => undefined };
      timers.push(timer);
      return timer;
    },
    clearTimeout: (timer) => {
      void timer;
    },
  });
  return { instance, states, timers };
}

describe("Computer Use 的状态与急停", () => {
  it("一次动作点亮「被控制中」,闲置到期自动熄灭", () => {
    const { instance, states, timers } = guard();
    instance.noteActivity();
    expect(instance.isActive()).toBe(true);
    expect(states).toEqual(["active:open:started"]);
    expect(timers.at(-1)?.ms).toBe(1000);

    timers.at(-1)!.fn(); // 闲置到期
    expect(instance.isActive()).toBe(false);
    expect(states.at(-1)).toBe("off:open:idle");
  });

  it("连续动作刷新闲置计时,不重复通知显示层", () => {
    const { instance, states } = guard();
    instance.noteActivity();
    instance.noteActivity();
    expect(instance.isActive()).toBe(true);
    expect(states).toEqual(["active:open:started"]);
  });

  it("急停挡住之后所有动作 —— 不是「歇一会儿」,要用户明确恢复", () => {
    const { instance } = guard();
    instance.noteActivity();
    instance.stop("hotkey");
    expect(instance.isActive()).toBe(false);
    expect(instance.isStopped()).toBe(true);

    expect(() => instance.noteActivity()).toThrow(/stopped by the user/);
    expect(instance.isActive()).toBe(false);

    expect(instance.resume()).toBe(true);
    expect(instance.isStopped()).toBe(false);
    expect(() => instance.noteActivity()).not.toThrow();
  });

  it("重复急停 / 未停就恢复:没有副作用", () => {
    const { instance } = guard();
    instance.noteActivity();
    expect(instance.stop()).toBe(true);
    expect(instance.stop()).toBe(false);
    expect(instance.resume()).toBe(true);
    expect(instance.resume()).toBe(false);
  });

  it("dispose 之后不再点亮(退出时把定时器收掉)", () => {
    const { instance } = guard();
    instance.dispose();
    expect(instance.isActive()).toBe(false);
    expect(instance.isStopped()).toBe(true);
  });
});
