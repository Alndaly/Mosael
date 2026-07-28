import { app, session, WebContentsView, type BaseWindow } from "electron";
import fs from "node:fs";
import path from "node:path";
import { EMBED_HEADER_HEIGHT, type ViewState } from "./types";
import { PageDriver } from "./pageDriver";

const noop = (): void => undefined;
// 账号视图 preload:注入「← 返回 Open Studio」悬浮按钮(见 electron/accountview-preload.cjs)。运行时
// 该文件与打包出的 publish.bundle.cjs 同在 electron/ 下,故按 __dirname 定位。
const ACCOUNT_VIEW_PRELOAD = path.join(__dirname, "accountview-preload.cjs");

/** 发布账号登录分区前缀(完整名 persist:<PARTITION_PREFIX>-<accountId>)。
 *  必须与后端 app/core/db.py 的 PARTITION_PREFIX 一致 —— 两边拼的是同一个磁盘目录。 */
export const PARTITION_PREFIX = "openstudio";
const LEGACY_PARTITION_PREFIX = "mibu";

/**
 * 更名遗留分区目录的**惰性**迁移:persist:openstudio-X 首次被用到时,若它的目录还不存在、
 * 而老的 mibu-X 目录在,就地改名。
 *
 * 为什么惰性而不是启动时批量:分区名同时记在数据库(后端改)和磁盘(这里改),两个进程各改一半。
 * 任何"先改一边"的方案都存在空窗——库里已指向新名、磁盘还是老名 → Electron 开出一个空分区,
 * 表现为全部平台登录失效。改成"用到谁迁谁",顺序就无关紧要了,且天然幂等。
 */
export function migrateLegacyPartitionDir(partition: string): void {
  const name = partition.startsWith("persist:") ? partition.slice("persist:".length) : partition;
  if (!name.startsWith(`${PARTITION_PREFIX}-`)) return;
  try {
    const root = path.join(app.getPath("userData"), "Partitions");
    const target = path.join(root, name);
    if (fs.existsSync(target)) return;
    const legacy = path.join(root, `${LEGACY_PARTITION_PREFIX}-${name.slice(PARTITION_PREFIX.length + 1)}`);
    if (fs.existsSync(legacy)) fs.renameSync(legacy, target);
  } catch (err) {
    // 迁移失败不该挡住登录流程:最坏情况是这个档案要重新登录一次。
    console.warn("[open-studio] partition dir migration skipped", partition, err);
  }
}

const platformUserAgent = (userAgent: string): string => {
  return userAgent.replace(/\sElectron\/[\d.]+/i, "");
};

/**
 * Owns one embedded WebContentsView per account. Each view uses a persistent
 * session partition (`persist:openstudio-<id>`) so cookies / localStorage are isolated
 * and survive restarts — this replaces the old Playwright per-account profile
 * directory. The view is laid into the host BaseWindow below a fixed header
 * strip that the renderer keeps clear for its own controls.
 */
export class AccountViewManager {
  private views = new Map<string, WebContentsView>();
  private drivers = new Map<string, PageDriver>();
  private appliedProxy = new Map<string, string | null>();
  // 泛化:非发布账号的视图(浏览器池通用档案)显式登记其分区与显示名;发布账号不登记,
  // 沿用 persist:openstudio-<accountId>。这样同一套内嵌视图既服务发布登录、也服务池档案登录。
  private partitions = new Map<string, string>();
  private names = new Map<string, string>();
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

  /** 通用:在给定分区开一个内嵌视图、亮出并导航到 url —— 供「浏览器池」通用档案登录复用**同一套**
   *  内嵌视图(与发布账号登录一致:同容器、同「返回 Open Studio」、同顶栏工具条),不弹外部系统窗。
   *  viewId 用分区名(唯一,且不与发布 accountId 冲突)。 */
  async openView(opts: { viewId: string; partition: string; name?: string; url: string; proxy?: string | null }): Promise<void> {
    // 池档案的分区名直接来自数据库,不经 partitionFor,故这里也要触发一次遗留目录迁移。
    migrateLegacyPartitionDir(opts.partition);
    this.partitions.set(opts.viewId, opts.partition);
    if (opts.name) this.names.set(opts.viewId, opts.name);
    const normalizedProxy = opts.proxy?.trim() || null;
    if (this.appliedProxy.get(opts.partition) !== normalizedProxy) {
      const viewSession = session.fromPartition(opts.partition);
      await viewSession.setProxy({
        mode: normalizedProxy ? "fixed_servers" : "direct",
        proxyRules: normalizedProxy ?? undefined,
      });
      this.appliedProxy.set(opts.partition, normalizedProxy);
    }
    const { view } = this.ensure(opts.viewId);
    this.show(opts.viewId);
    const url = normalizeAddress(opts.url);
    if (url) void view.webContents.loadURL(url);
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
    console.info("[open-studio:view] shown", {
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

  private visibleWebContents(): Electron.WebContents | null {
    const view = this.visibleId ? this.views.get(this.visibleId) : null;
    return view && !view.webContents.isDestroyed() ? view.webContents : null;
  }

  /** 工具栏导航:全部作用于当前可见视图,内部动作发生在「已聚焦的视图」里,稳。 */
  navigate(rawUrl: string): void {
    const wc = this.visibleWebContents();
    if (!wc) return;
    const url = normalizeAddress(rawUrl);
    if (url) void wc.loadURL(url);
  }
  back(): void {
    this.visibleWebContents()?.navigationHistory.goBack();
  }
  forward(): void {
    this.visibleWebContents()?.navigationHistory.goForward();
  }
  reload(): void {
    const wc = this.visibleWebContents();
    if (!wc) return;
    if (wc.isLoading()) wc.stop();
    else wc.reload();
  }

  /**
   * Open detached DevTools on an account's embedded view (or the currently
   * visible one) — used to probe/calibrate selectors against the live platform
   * DOM. Toggles: a second call on an already-open inspector closes it.
   */
  openDevTools(accountId?: string): boolean {
    const id = accountId ?? this.visibleId;
    const view = id ? this.views.get(id) : null;
    if (!view || view.webContents.isDestroyed()) {
      return false;
    }
    const wc = view.webContents;
    if (wc.isDevToolsOpened()) {
      wc.closeDevTools();
    } else {
      wc.openDevTools({ mode: "detach" });
    }
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
        console.warn("[open-studio:view] load failed", {
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
      // 地址/加载态变化 → 刷新工具栏(仅当前可见视图才广播)。
      const sync = () => {
        if (this.visibleId === accountId) this.emit();
      };
      view.webContents.on("did-navigate", sync);
      view.webContents.on("did-navigate-in-page", sync);
      view.webContents.on("did-start-loading", sync);
      view.webContents.on("did-stop-loading", sync);
      view.setBackgroundColor("#ffffff");
      this.views.set(accountId, view);
      this.drivers.set(accountId, new PageDriver(view.webContents));
    }
    return { view, driver: this.drivers.get(accountId)! };
  }

  private partitionFor(id: string): string {
    // 登记过的(池档案)用其显式分区;未登记的(发布账号)按约定 persist:<prefix>-<id>。
    const partition = this.partitions.get(id) ?? `persist:${PARTITION_PREFIX}-${id}`;
    // 拿分区名的每条路径最终都会落到这里,所以遗留目录的惰性改名挂在这一处即可(幂等)。
    migrateLegacyPartitionDir(partition);
    return partition;
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
    const wc = this.visibleWebContents();
    this.onViewChanged({
      visible: this.visibleId !== null,
      accountId: this.visibleId,
      accountName: this.visibleId ? this.names.get(this.visibleId) ?? this.nameOf(this.visibleId) : null,
      url: wc ? wc.getURL() : "",
      canGoBack: wc ? wc.navigationHistory.canGoBack() : false,
      canGoForward: wc ? wc.navigationHistory.canGoForward() : false,
      loading: wc ? wc.isLoading() : false,
    });
  }
}

/** 地址栏输入归一化:补协议、看着像域名就直接访问,否则丢给必应搜索。 */
function normalizeAddress(input: string): string | null {
  const value = input.trim();
  if (!value) return null;
  if (/^https?:\/\//i.test(value)) return value;
  // 形如 example.com / localhost:3000 / 带路径的裸域名 → 补 https。
  if (/^[\w-]+(\.[\w-]+)+(:\d+)?(\/.*)?$/.test(value) || /^localhost(:\d+)?(\/.*)?$/i.test(value)) {
    return `https://${value}`;
  }
  return `https://www.bing.com/search?q=${encodeURIComponent(value)}`;
}
