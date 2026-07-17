import { session, WebContentsView, type BaseWindow } from "electron";
import path from "node:path";
import { EMBED_HEADER_HEIGHT, type ViewState } from "./types";
import { PageDriver } from "./pageDriver";

const noop = (): void => undefined;
// 账号视图 preload:注入「← 返回 Mibu」悬浮按钮(见 electron/accountview-preload.cjs)。运行时该文件
// 与打包出的 publish.bundle.cjs 同在 electron/ 下,故按 __dirname 定位。
const ACCOUNT_VIEW_PRELOAD = path.join(__dirname, "accountview-preload.cjs");

const platformUserAgent = (userAgent: string): string => {
  return userAgent.replace(/\sElectron\/[\d.]+/i, "");
};

/**
 * Owns one embedded WebContentsView per account. Each view uses a persistent
 * session partition (`persist:mibu-<id>`) so cookies / localStorage are isolated
 * and survive restarts — this replaces the old Playwright per-account profile
 * directory. The view is laid into the host BaseWindow below a fixed header
 * strip that the renderer keeps clear for its own controls.
 */
export class AccountViewManager {
  private views = new Map<string, WebContentsView>();
  private drivers = new Map<string, PageDriver>();
  private appliedProxy = new Map<string, string | null>();
  private window: BaseWindow | null = null;
  private visibleId: string | null = null;
  private nameOf: (accountId: string) => string | null = () => null;

  constructor(private readonly onViewChanged: (state: ViewState) => void = noop) {}

  attachWindow(window: BaseWindow, nameResolver: (accountId: string) => string | null): void {
    this.window = window;
    this.nameOf = nameResolver;
    window.on("resize", () => this.layout());
  }

  getDriver(accountId: string): PageDriver {
    return this.ensure(accountId).driver;
  }

  async configureAccount(accountId: string, proxy: string | null): Promise<void> {
    this.ensure(accountId);
    const partition = this.partitionFor(accountId);
    const normalizedProxy = proxy?.trim() || null;
    if (this.appliedProxy.get(partition) === normalizedProxy) {
      return;
    }
    const accountSession = session.fromPartition(partition);
    await accountSession.setProxy({
      mode: normalizedProxy ? "fixed_servers" : "direct",
      proxyRules: normalizedProxy ?? undefined,
    });
    this.appliedProxy.set(partition, normalizedProxy);
  }

  /** Bring an account's view to the front of the window and size it. */
  show(accountId: string): void {
    const { view } = this.ensure(accountId);
    if (!this.window || this.window.isDestroyed()) {
      return;
    }
    if (this.visibleId && this.visibleId !== accountId) {
      this.detachView(this.visibleId);
    }
    this.visibleId = accountId;
    this.layout();
    // Re-adding the same View is the current View API's z-order operation:
    // Electron reorders it to the topmost child of the window content view.
    this.window.contentView.addChildView(view);
    console.info("[mibu:view] shown", {
      accountId,
      bounds: view.getBounds(),
      childCount: this.window.contentView.children.length,
      url: view.webContents.getURL(),
    });
    this.emit();
  }

  /** Hide whatever view is currently shown (returns the window to the React UI). */
  hide(): void {
    if (this.visibleId) {
      this.detachView(this.visibleId);
      this.visibleId = null;
      this.emit();
    }
  }

  get visibleAccountId(): string | null {
    return this.visibleId;
  }

  /**
   * Open detached DevTools on the currently visible embedded view (menu-driven;
   * used to probe/calibrate selectors against the live platform DOM).
   */
  openDevTools(): boolean {
    const view = this.visibleId ? this.views.get(this.visibleId) : null;
    if (!view || view.webContents.isDestroyed()) {
      return false;
    }
    view.webContents.openDevTools({ mode: "detach" });
    return true;
  }

  destroy(accountId: string): void {
    this.detachView(accountId);
    this.drivers.get(accountId)?.detach();
    const view = this.views.get(accountId);
    if (view) {
      try {
        view.webContents.close();
      } catch {
        // already gone
      }
    }
    this.views.delete(accountId);
    this.drivers.delete(accountId);
    if (this.visibleId === accountId) {
      this.visibleId = null;
      this.emit();
    }
  }

  /** Wipe the account's persisted login state (cookies, localStorage, caches). */
  async clearAccountData(accountId: string): Promise<void> {
    this.destroy(accountId);
    const partition = this.partitionFor(accountId);
    this.appliedProxy.delete(partition);
    const accountSession = session.fromPartition(partition);
    await accountSession.clearStorageData();
    await accountSession.clearCache().catch(noop);
  }

  destroyAll(): void {
    for (const accountId of [...this.views.keys()]) {
      this.destroy(accountId);
    }
  }

  private ensure(accountId: string): { view: WebContentsView; driver: PageDriver } {
    let view = this.views.get(accountId);
    if (!view) {
      view = new WebContentsView({
        webPreferences: {
          partition: this.partitionFor(accountId),
          backgroundThrottling: false,
          // 注入「返回」悬浮按钮(点击永远发生在聚焦的账号视图内,不会被 macOS 焦点切换吞掉)。
          preload: ACCOUNT_VIEW_PRELOAD,
          contextIsolation: true,
        },
      });
      view.webContents.setUserAgent(platformUserAgent(view.webContents.getUserAgent()));
      view.webContents.setWindowOpenHandler(({ url }) => {
        // 弹窗只允许 http(s) 在本视图内导航;javascript:/file:/data: 等危险 scheme 一律不加载,
        // 免得平台页面的 window.open 把已登录会话视图导到任意/危险目标。
        try {
          const proto = new URL(url).protocol;
          if (proto === "http:" || proto === "https:") void view?.webContents.loadURL(url);
        } catch {
          /* 非法 URL,忽略 */
        }
        return { action: "deny" };
      });
      view.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedURL) => {
        console.warn("[mibu:view] load failed", {
          accountId,
          errorCode,
          errorDescription,
          url: validatedURL,
        });
      });
      // Esc 从内嵌视图内可靠返回:顶栏「返回」是主窗口 HTML,内嵌视图抢焦点后首次点击常被 macOS
      // 吃掉(时灵时不灵)。Esc 直接在视图 webContents 上收——无论焦点在谁那儿都稳。
      view.webContents.on("before-input-event", (_event, input) => {
        if (input.type === "keyDown" && input.key === "Escape") this.hide();
      });
      view.setBackgroundColor("#ffffff");
      this.views.set(accountId, view);
      this.drivers.set(accountId, new PageDriver(view.webContents));
    }
    return { view, driver: this.drivers.get(accountId)! };
  }

  private partitionFor(accountId: string): string {
    return `persist:mibu-${accountId}`;
  }

  private detachView(accountId: string): void {
    const view = this.views.get(accountId);
    if (view && this.window && !this.window.isDestroyed()) {
      this.window.contentView.removeChildView(view);
    }
  }

  private layout(): void {
    if (!this.window || this.window.isDestroyed() || !this.visibleId) {
      return;
    }
    const view = this.views.get(this.visibleId);
    if (!view) {
      return;
    }
    const [width, height] = this.window.getContentSize();
    view.setBounds({
      x: 0,
      y: EMBED_HEADER_HEIGHT,
      width,
      height: Math.max(0, height - EMBED_HEADER_HEIGHT),
    });
  }

  private emit(): void {
    this.onViewChanged({
      visible: this.visibleId !== null,
      accountId: this.visibleId,
      accountName: this.visibleId ? this.nameOf(this.visibleId) : null,
    });
  }
}
