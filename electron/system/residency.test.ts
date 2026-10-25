import { EventEmitter } from "node:events";

import { describe, expect, it, vi } from "vitest";

import { residency } from "./residency";
vi.mock("electron", () => ({
  app: { on: vi.fn(), off: vi.fn() },
}));

describe("常驻退出", () => {
  it("宿主开始退出并注销能力后,不再把窗口关闭拦成隐藏", () => {
    const win = Object.assign(new EventEmitter(), {
      hide: vi.fn(),
      isDestroyed: () => false,
    });
    const handle = residency.register({ getWindow: () => win } as never);

    const ordinaryClose = { preventDefault: vi.fn() };
    win.emit("close", ordinaryClose);
    expect(ordinaryClose.preventDefault).toHaveBeenCalledTimes(1);
    expect(win.hide).toHaveBeenCalledTimes(1);

    // main.cjs 的 before-quit 先 dispose 系统能力;residency 自己注册的
    // before-quit 监听此时已经被移除,不能再依赖它稍后补记退出状态。
    handle?.dispose();
    const quitClose = { preventDefault: vi.fn() };
    win.emit("close", quitClose);

    expect(quitClose.preventDefault).not.toHaveBeenCalled();
    expect(win.hide).toHaveBeenCalledTimes(1);
  });
});
