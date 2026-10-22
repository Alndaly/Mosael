/**
 * Computer Use 的屏幕四角描边(ADR 0075 安全 2)。
 *
 * 不建真的窗口:这里用替身 BrowserWindow / screen,钉住 —— 每个显示器一块、透明且**不接鼠标**
 * (点了会穿透到下面的页面)、不抢焦点;显示/收掉各做一次(重复调用不叠窗口);文字进 HTML 前转义。
 */
import { describe, expect, it, vi } from "vitest";

// CommonJS is intentional: main.cjs loads this exact module.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createComputerUseOverlay, computerUseOverlayHtml } = require("./computerUseOverlay.cjs") as {
  createComputerUseOverlay: (options: {
    BrowserWindow: new (options: Record<string, unknown>) => {
      setIgnoreMouseEvents: (value: boolean) => void;
      setAlwaysOnTop: (value: boolean, level: string) => void;
      loadURL: (url: string) => Promise<void>;
      once: (event: string, listener: () => void) => void;
      showInactive: () => void;
      destroy: () => void;
      options: Record<string, unknown>;
      shown: boolean;
      destroyed: boolean;
    };
    screen: { getAllDisplays: () => Array<{ bounds: { x: number; y: number; width: number; height: number } }> };
    label: () => string;
  }) => { show: () => void; hide: () => void; count: () => number };
  computerUseOverlayHtml: (label: string) => string;
};

function fakeElectron(displays: number) {
  const created: Array<{
    setIgnoreMouseEvents: ReturnType<typeof vi.fn>;
    setAlwaysOnTop: ReturnType<typeof vi.fn>;
    loadURL: ReturnType<typeof vi.fn>;
    once: ReturnType<typeof vi.fn>;
    showInactive: ReturnType<typeof vi.fn>;
    destroy: ReturnType<typeof vi.fn>;
    options: Record<string, unknown>;
  }> = [];
  class FakeBrowserWindow {
    options: Record<string, unknown>;
    setIgnoreMouseEvents = vi.fn();
    setAlwaysOnTop = vi.fn();
    loadURL = vi.fn(async () => undefined);
    once = vi.fn();
    showInactive = vi.fn();
    destroy = vi.fn();
    constructor(options: Record<string, unknown>) {
      this.options = options;
      created.push(this);
    }
  }
  const screen = {
    getAllDisplays: () => Array.from({ length: displays }, (_, index) => ({ bounds: { x: index * 1920, y: 0, width: 1920, height: 1080 } })),
  };
  return { BrowserWindow: FakeBrowserWindow, screen, created };
}

describe("屏幕四角描边", () => {
  it("每个显示器一块,透明、不接鼠标、不抢焦点,显示再收掉", () => {
    const { BrowserWindow, screen, created } = fakeElectron(2);
    const overlay = createComputerUseOverlay({ BrowserWindow, screen, label: () => "Computer Use 正在操作 Mosael" });

    overlay.show();
    expect(created).toHaveLength(2);
    expect(created[0].options).toMatchObject({
      frame: false,
      transparent: true,
      focusable: false,
      skipTaskbar: true,
      hasShadow: false,
    });
    expect(created[0].setIgnoreMouseEvents).toHaveBeenCalledWith(true);
    expect(created[0].setAlwaysOnTop).toHaveBeenCalledWith(true, "screen-saver");

    overlay.show(); // 重复显示不叠窗口
    expect(created).toHaveLength(2);

    overlay.hide();
    expect(created[0].destroy).toHaveBeenCalled();
    expect(overlay.count()).toBe(0);
  });

  it("文字进 HTML 前转义(标签名来自界面文案,不该被当成结构)", () => {
    expect(computerUseOverlayHtml('<b x="1">')).not.toMatch(/<b x=/);
    expect(computerUseOverlayHtml('<b x="1">')).toMatch(/&lt;b x=&quot;1&quot;&gt;/);
  });
});
