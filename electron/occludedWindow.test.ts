import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const MAIN = fs.readFileSync(path.resolve(__dirname, "main.cjs"), "utf8");

describe("窗口被挡住时,浏览器自动化照常渲染", () => {
  /**
   * 浏览器自动化的会话视图挂在主窗口里(右下角面板)。Chromium 在 macOS 上把**被别的窗口挡住、或不在当前桌面**的
   * 窗口当成隐藏:document.visibilityState 变成 hidden,不再出帧 —— scroll 事件、IntersectionObserver 都停了,
   * 靠滚动加载的列表、评论区不再往下加载。
   *
   * 实测(2026-10,真实执行器):Mosael 在别的窗口后面时,同一张本地测试页滚到底也只有 10 条(应为 20 条),
   * B 站评论区读页面那一路从 33 条一级评论掉到 3 条;工作流本来就是让人切走去干别的才跑的。
   * 只关「被挡住算隐藏」这一条:最小化、窗口关掉照旧按隐藏处理。
   */
  it("启动开关里关掉「被挡住的窗口按隐藏处理」,而且在 app ready 之前", () => {
    const at = MAIN.indexOf('app.commandLine.appendSwitch("disable-backgrounding-occluded-windows")');
    expect(at).toBeGreaterThan(-1);
    const ready = MAIN.search(/app\.whenReady\(|app\.on\("ready"/);
    expect(ready === -1 || at < ready).toBe(true);
    expect(at).toBeLessThan(MAIN.indexOf("app.requestSingleInstanceLock()"));
  });
});
