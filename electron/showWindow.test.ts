/**
 * 叫回主窗口(main.cjs 的 showWindow)。
 *
 * 关窗只是藏起来(system/residency):窗口一直在。macOS 点 Dock 图标发的是 `activate`,此前它只在「一个窗口都没有」
 * 时才建窗口 —— 藏起来的窗口点 Dock 叫不回来,只有菜单栏的托盘图标能打开。现在 activate 和托盘走同一个 showWindow。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

import { describe, expect, it, vi } from "vitest";

const MAIN = fs.readFileSync(path.join(__dirname, "main.cjs"), "utf8");

/** 从 main.cjs 里取出 showWindow 本身,配上假的 BrowserWindow / createWindow 跑。 */
function loadShowWindow(windows: FakeWindow[], createWindow = vi.fn(), mainWindow: FakeWindow | null = windows[0] ?? null) {
  const source = MAIN.match(/\nfunction showWindow\(\) \{[\s\S]*?\n\}\n/)?.[0];
  if (!source) throw new Error("showWindow not found in main.cjs");
  const context = {
    BrowserWindow: { getAllWindows: () => windows },
    mainWindow,
    createWindow: () => {
      createWindow();
      if (!context.mainWindow || context.mainWindow.isDestroyed()) {
        context.mainWindow = windows.at(-1) ?? null;
      }
    },
    showWindow: undefined as undefined | (() => void),
  };
  vm.runInNewContext(`${source}; this.showWindow = showWindow;`, context);
  return { showWindow: context.showWindow!, createWindow };
}

type FakeWindow = ReturnType<typeof fakeWindow>;
function fakeWindow({ visible = true, minimized = false, destroyed = false } = {}) {
  const win = {
    visible,
    minimized,
    destroyed,
    isDestroyed: () => win.destroyed,
    isMinimized: () => win.minimized,
    restore: vi.fn(() => (win.minimized = false)),
    show: vi.fn(() => (win.visible = true)),
    focus: vi.fn(),
  };
  return win;
}

describe("叫回主窗口", () => {
  it("关窗之后藏着的窗口:亮出来、拿到焦点,不另建一个", () => {
    const hidden = fakeWindow({ visible: false });
    const { showWindow, createWindow } = loadShowWindow([hidden]);
    showWindow();
    expect(hidden.visible).toBe(true);
    expect(hidden.focus).toHaveBeenCalled();
    expect(createWindow).not.toHaveBeenCalled();
  });

  it("最小化的:先还原", () => {
    const minimized = fakeWindow({ minimized: true });
    const { showWindow } = loadShowWindow([minimized]);
    showWindow();
    expect(minimized.restore).toHaveBeenCalled();
  });

  it("一个窗口都没有:建一个", () => {
    const windows: FakeWindow[] = [];
    const createWindow = vi.fn(() => windows.push(fakeWindow()));
    loadShowWindow(windows, createWindow).showWindow();
    expect(createWindow).toHaveBeenCalledOnce();
  });

  it("启动小窗排在窗口列表首位:仍然叫回真正的主窗口", () => {
    const splash = fakeWindow();
    const main = fakeWindow({ visible: false });
    const { showWindow } = loadShowWindow([splash, main], vi.fn(), main);
    showWindow();
    expect(main.visible).toBe(true);
    expect(main.focus).toHaveBeenCalled();
    expect(splash.show).not.toHaveBeenCalled();
  });

  it("主窗口已销毁:即使辅助窗还在也重建主窗口", () => {
    const splash = fakeWindow();
    const destroyed = fakeWindow({ destroyed: true });
    const windows = [splash, destroyed];
    const createWindow = vi.fn(() => windows.push(fakeWindow()));
    loadShowWindow(windows, createWindow, destroyed).showWindow();
    expect(createWindow).toHaveBeenCalledOnce();
    expect(splash.show).not.toHaveBeenCalled();
  });

  it("点 Dock(activate)和托盘「打开 Mosael」走同一个 showWindow", () => {
    expect(MAIN).toMatch(/app\.on\("activate", \(\) => showWindow\(\)\)/);
    expect(MAIN).toMatch(/registerSystemCapabilities\(\{[\s\S]{0,200}showWindow,/);
  });
});
