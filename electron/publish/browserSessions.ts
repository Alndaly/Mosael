import path from "node:path";

import { BrowserWindow } from "electron";

import { PageDriver } from "./pageDriver";

// 复用发布视图的反检测补丁(navigator.webdriver/plugins/WebGL 等),RPA 打防御站点同样受益。
const RPA_VIEW_PRELOAD = path.join(__dirname, "account-view-preload.cjs");
const stripElectron = (ua: string): string => ua.replace(/ Electron\/[0-9.]+/g, "");

/**
 * RPA / 智能体自动化的浏览器会话管理:每个会话一个**隐藏的离屏(OSR)BrowserWindow** + 一个
 * PageDriver。为什么用 BrowserWindow 而不是 WebContentsView:后者不支持 offscreen 渲染,不挂窗口
 * 时根本不出帧(capturePage 空、paint 不触发),预览就无从谈起;OSR BrowserWindow 才是官方的
 * 「不显示也持续渲染」原语——show:false + offscreen:true,paint 事件出帧,PageDriver 据此缓存供
 * 预览/截图。分区只会是 ephemeral-*(内存态)或 persist:rpa-*,与发布 persist:openstudio-* 严格隔离。
 */
export class BrowserSessionManager {
  private windows = new Map<string, BrowserWindow>();
  private drivers = new Map<string, PageDriver>();

  // 不需要宿主窗口:RPA 会话用的是 offscreen BrowserWindow,离屏渲染本身就持续出帧(见
  // browserWorker.capturePreview),不必挂到主窗口里参与合成——发布账号视图那条路才有这个约束。
  constructor() {}

  ensure(sessionId: string, partition: string): PageDriver {
    const existing = this.drivers.get(sessionId);
    if (existing) return existing;
    const win = new BrowserWindow({
      show: false, // 永不显示;offscreen 保证仍持续渲染出帧
      width: 1280,
      height: 800,
      webPreferences: {
        partition,
        offscreen: true,
        backgroundThrottling: false,
        preload: RPA_VIEW_PRELOAD,
        contextIsolation: true,
      },
    });
    try {
      win.webContents.setFrameRate(5); // 离屏 5fps 足够预览,省 GPU
    } catch {
      /* 忽略 */
    }
    win.webContents.setUserAgent(stripElectron(win.webContents.getUserAgent()));
    win.webContents.setWindowOpenHandler(({ url }) => {
      try {
        const proto = new URL(url).protocol;
        if (proto === "http:" || proto === "https:") void win.webContents.loadURL(url);
      } catch {
        /* 非法 URL,忽略 */
      }
      return { action: "deny" };
    });
    this.windows.set(sessionId, win);
    const driver = new PageDriver(win.webContents);
    this.drivers.set(sessionId, driver);
    return driver;
  }

  /** 已存在的会话驱动(不新建);用于预览截帧等。 */
  getDriver(sessionId: string): PageDriver | null {
    return this.drivers.get(sessionId) ?? null;
  }

  destroy(sessionId: string): void {
    this.drivers.get(sessionId)?.detach();
    const win = this.windows.get(sessionId);
    try {
      if (win && !win.isDestroyed()) win.destroy();
    } catch {
      /* 已销毁,忽略 */
    }
    this.windows.delete(sessionId);
    this.drivers.delete(sessionId);
  }

  destroyAll(): void {
    for (const id of [...this.windows.keys()]) this.destroy(id);
  }
}
