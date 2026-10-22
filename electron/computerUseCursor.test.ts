/**
 * Computer Use 的指针提示:动手时在窗口里那个点上亮一枚指针(ADR 0075 安全 2 的延伸)。
 *
 * 纯模块,不建真窗口:这里钉住「亮在哪里、亮多久、不叠窗口、拍图拍不到它(它不属于页面)」。
 */
import { describe, expect, it, vi } from "vitest";

// CommonJS is intentional: main.cjs loads this exact module.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createComputerUseCursor } = require("./computerUseCursor.cjs") as {
  createComputerUseCursor: (options: {
    BrowserWindow: new (options: Record<string, unknown>) => {
      options: Record<string, unknown>;
      setIgnoreMouseEvents: ReturnType<typeof vi.fn>;
      setAlwaysOnTop: ReturnType<typeof vi.fn>;
      loadURL: ReturnType<typeof vi.fn>;
      setPosition: ReturnType<typeof vi.fn>;
      showInactive: ReturnType<typeof vi.fn>;
      hide: ReturnType<typeof vi.fn>;
      destroy: ReturnType<typeof vi.fn>;
      isDestroyed: () => boolean;
      webContents: { executeJavaScript: ReturnType<typeof vi.fn> };
    };
    size?: number;
    holdMs?: number;
    setTimer?: (fn: () => void, ms: number) => number;
    clearTimer?: (timer: number) => void;
  }) => { showAt: (x: number, y: number, kind?: string) => boolean; hide: () => void; dispose: () => void };
};

function fakeElectron() {
  const created: Array<{
    options: Record<string, unknown>;
    setIgnoreMouseEvents: ReturnType<typeof vi.fn>;
    setAlwaysOnTop: ReturnType<typeof vi.fn>;
    loadURL: ReturnType<typeof vi.fn>;
    setPosition: ReturnType<typeof vi.fn>;
    showInactive: ReturnType<typeof vi.fn>;
    hide: ReturnType<typeof vi.fn>;
    destroy: ReturnType<typeof vi.fn>;
    isDestroyed: () => boolean;
    webContents: { executeJavaScript: ReturnType<typeof vi.fn> };
  }> = [];
  class FakeBrowserWindow {
    options: Record<string, unknown>;
    setIgnoreMouseEvents = vi.fn();
    setAlwaysOnTop = vi.fn();
    loadURL = vi.fn(async () => undefined);
    setPosition = vi.fn();
    showInactive = vi.fn();
    hide = vi.fn();
    destroy = vi.fn();
    destroyCalled = false;
    webContents = { executeJavaScript: vi.fn(async () => undefined) };
    constructor(options: Record<string, unknown>) {
      this.options = options;
      created.push(this);
    }
    isDestroyed() {
      return this.destroyCalled;
    }
  }
  return { BrowserWindow: FakeBrowserWindow, created };
}

function timers() {
  let pending: Array<() => void> = [];
  return {
    setTimer: (fn: () => void) => {
      pending.push(fn);
      return pending.length;
    },
    clearTimer: (timer: number) => {
      pending = pending.filter((_, index) => index !== timer - 1);
    },
    fire: () => pending.splice(0).forEach((fn) => fn()),
    get pending() {
      return pending.length;
    },
  };
}

describe("鼠标位置的指针提示", () => {
  it("指针尖端落在那个点上:窗口左上角偏出一点点,亮一下、不接鼠标、不抢焦点", () => {
    const { BrowserWindow, created } = fakeElectron();
    const tick = timers();
    const cursor = createComputerUseCursor({ BrowserWindow, setTimer: tick.setTimer, clearTimer: tick.clearTimer });

    expect(cursor.showAt(640, 360, "click")).toBe(true);
    expect(created).toHaveLength(1);
    expect(created[0].options).toMatchObject({
      frame: false,
      transparent: true,
      focusable: false,
      skipTaskbar: true,
      hasShadow: false,
    });
    expect(created[0].setIgnoreMouseEvents).toHaveBeenCalledWith(true);
    expect(created[0].setAlwaysOnTop).toHaveBeenCalledWith(true, "screen-saver");
    // 尖端在窗口左上那一枚指针的尖端:窗口左上角比点略偏左上,而不是把窗口铺在点上。
    expect(created[0].setPosition).toHaveBeenCalledWith(636, 356);
    expect(created[0].showInactive).toHaveBeenCalledTimes(1);
  });

  it("连续动作只用一个窗口,每次重新亮;到点自己收起来", () => {
    const { BrowserWindow, created } = fakeElectron();
    const tick = timers();
    const cursor = createComputerUseCursor({ BrowserWindow, setTimer: tick.setTimer, clearTimer: tick.clearTimer });

    cursor.showAt(100, 100);
    cursor.showAt(300, 200, "scroll-down");
    expect(created).toHaveLength(1);
    expect(created[0].setPosition).toHaveBeenLastCalledWith(296, 196);
    expect(created[0].showInactive).toHaveBeenCalledTimes(2);
    expect(created[0].webContents.executeJavaScript).toHaveBeenLastCalledWith(
      expect.stringContaining("scroll-down"),
    );

    tick.fire();
    expect(created[0].hide).toHaveBeenCalledTimes(1);
  });

  it("dispose 收掉窗口;hide 只藏不销毁", () => {
    const { BrowserWindow, created } = fakeElectron();
    const tick = timers();
    const cursor = createComputerUseCursor({ BrowserWindow, setTimer: tick.setTimer, clearTimer: tick.clearTimer });

    cursor.showAt(10, 20);
    cursor.hide();
    expect(created[0].hide).toHaveBeenCalled();
    expect(created[0].destroy).not.toHaveBeenCalled();

    cursor.showAt(10, 20);
    cursor.dispose();
    expect(created[0].destroy).toHaveBeenCalled();
  });
});
