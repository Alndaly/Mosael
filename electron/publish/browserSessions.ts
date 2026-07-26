import path from "node:path";

import { WebContentsView, type BaseWindow } from "electron";

import { PageDriver } from "./pageDriver";

// 复用发布视图的反检测补丁(navigator.webdriver/plugins/WebGL 等),RPA 打防御站点同样受益。
const RPA_VIEW_PRELOAD = path.join(__dirname, "accountview-preload.cjs");
const stripElectron = (ua: string): string => ua.replace(/ Electron\/[0-9.]+/g, "");

/**
 * RPA / 智能体自动化的浏览器会话管理:每个会话一个 WebContentsView(在后端下发的隔离分区上)
 * + 一个 PageDriver。与发布(AccountViewManager)彻底分开:
 * - 分区只会是 ephemeral-*(内存态)或 persist:rpa-*(具名持久),**绝不是 persist:mibu-***(发布);
 * - 视图默认 headless(不加进窗口),Phase 0 的 DOM 级动作(导航/点击/输入/提取/等待/求值)
 *   在离屏视图上即可驱动(与发布后台流一致);坐标点击/截图/实时预览留到 Phase 3 再加离屏 bounds。
 */
export class BrowserSessionManager {
  private views = new Map<string, WebContentsView>();
  private drivers = new Map<string, PageDriver>();

  // window 供 Phase 3(实时预览/坐标动作需要把视图挂上窗口给离屏 bounds)使用。
  constructor(private readonly window: BaseWindow) {}

  ensure(sessionId: string, partition: string): PageDriver {
    const existing = this.drivers.get(sessionId);
    if (existing) return existing;
    const view = new WebContentsView({
      webPreferences: {
        partition,
        backgroundThrottling: false,
        preload: RPA_VIEW_PRELOAD,
        contextIsolation: true,
      },
    });
    view.webContents.setUserAgent(stripElectron(view.webContents.getUserAgent()));
    view.webContents.setWindowOpenHandler(({ url }) => {
      // window.open 只允许 http(s) 在本视图内导航;其它 scheme 一律拒绝。
      try {
        const proto = new URL(url).protocol;
        if (proto === "http:" || proto === "https:") void view.webContents.loadURL(url);
      } catch {
        /* 非法 URL,忽略 */
      }
      return { action: "deny" };
    });
    view.setBackgroundColor("#ffffff");
    this.views.set(sessionId, view);
    const driver = new PageDriver(view.webContents);
    this.drivers.set(sessionId, driver);
    return driver;
  }

  destroy(sessionId: string): void {
    this.drivers.get(sessionId)?.detach();
    const view = this.views.get(sessionId);
    try {
      view?.webContents?.close?.();
    } catch {
      /* 已销毁,忽略 */
    }
    this.views.delete(sessionId);
    this.drivers.delete(sessionId);
  }

  destroyAll(): void {
    for (const id of [...this.views.keys()]) this.destroy(id);
  }
}
