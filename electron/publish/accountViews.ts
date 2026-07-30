import { app, session, WebContentsView, type BaseWindow } from "electron";
import fs from "node:fs";
import path from "node:path";
import { EMBED_HEADER_HEIGHT, type ViewState } from "./types";
import { PageDriver } from "./pageDriver";

const noop = (): void => undefined;
// 账号视图 preload:注入「← 返回 Open Studio」悬浮按钮(见 electron/account-view-preload.cjs)。运行时
// 该文件与打包出的 publish.bundle.cjs 同在 electron/ 下,故按 __dirname 定位。
const ACCOUNT_VIEW_PRELOAD = path.join(__dirname, "account-view-preload.cjs");

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

/**
 * 后台任务的「悬浮面板」几何。
 *
 * 面板 384×240 + zoomFactor 0.3 → 页面**布局视口是 1280×800**(384/0.3),也就是平台页面按桌面版
 * 排版,而显示只占右下角一小块。这不是美观取舍,是必要条件:面板若不缩放地做成 384 宽,B 站会
 * 渲染窄屏版布局,选择器与整个流程都会变。
 *
 * 为什么要挂进窗口而不是留在后台:只有**参与合成**的视图才有真实布局和可用的命中测试 —— 挂上去
 * 之后真实指针输入(isTrusted=true)才生效,同时画面也是真的,不必再靠截图镜像。实测三个面板
 * 叠放(后加的压住先加的)时,被完全遮挡的那个照样有 1280×800 视口、照样能被可信点击命中。
 */
const PANEL = { width: 384, height: 240, zoom: 0.3, margin: 16, stackOffset: 20 } as const;

/**
 * 同时挂载的面板上限。挂载的视图是真在合成的页面,不是免费的 —— 智能体可能开很多路会话,全挂上去
 * 既吃 GPU 也把卡片堆推出窗口。超出上限的视图不挂载:它照样能跑(RPA 的动作走的是 DOM 事件,不
 * 依赖布局与命中测试),只是没有画面、也用不上可信输入。
 */
const MAX_PANELS = 4;

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
  // 正在以悬浮面板形式挂载的账号,按挂载顺序 —— 决定叠放次序(后挂的在上)。
  private panels: string[] = [];
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

  /**
   * 登记一个「非发布账号」的会话视图:显式指定分区,建好视图与驱动,但**不亮出来**。
   *
   * 供 RPA / 智能体会话复用同一套内嵌视图(此前它们自己起离屏 BrowserWindow —— 见已删除的
   * browserSessions.ts)。分区照旧严格隔离:ephemeral-*(内存态)/ persist:rpa-* 与发布的
   * persist:openstudio-* 互不相干。
   */
  registerSession(viewId: string, partition: string): PageDriver {
    migrateLegacyPartitionDir(partition);
    this.partitions.set(viewId, partition);
    return this.ensure(viewId).driver;
  }

  /** 已建好的驱动(不新建)。 */
  existingDriver(viewId: string): PageDriver | null {
    return this.drivers.get(viewId) ?? null;
  }

  /** Bring an account's view to the front of the window and size it. */
  show(accountId: string): void {
    const { view, driver } = this.ensure(accountId);
    if (!this.window || this.window.isDestroyed()) {
      return;
    }
    // 面板模式把 zoomFactor 压到 0.3;亮到前台必须还原成 1,否则整页缩成三成大小。
    // zoomFactor 是**按 origin 持久化**的(实测会泄漏到同源的其它视图),所以必须显式设回。
    view.webContents.setZoomFactor(1);
    void driver.clearMetricsOverride();
    if (this.visibleId && this.visibleId !== accountId) {
      this.demote(this.visibleId);
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
      // 顺序要紧:先清 visibleId 再 demote。panelAttach 对「正在前台的账号」有早退保护
      // (它不该去动前台视图),先 demote 就会被这条保护挡掉,任务还在跑却收不回面板。
      const previous = this.visibleId;
      this.visibleId = null;
      this.demote(previous);
      this.emit();
    }
  }

  /**
   * 把某账号视图挂成右下角的悬浮面板(任务执行期间的默认形态)。
   *
   * 挂载 = 参与合成 = 有真实布局与命中测试,于是可信指针输入(isTrusted=true)可用、画面也是真的。
   * 见 PANEL 常量的说明。已在前台全屏显示的账号不动它(它本来就在合成)。
   */
  panelAttach(accountId: string): boolean {
    if (!this.window || this.window.isDestroyed() || this.visibleId === accountId) {
      return false;
    }
    if (!this.panels.includes(accountId)) {
      if (this.panels.length >= MAX_PANELS) return false; // 见 MAX_PANELS:超额不挂,但任务照跑
      this.panels.push(accountId);
    }
    const { view } = this.ensure(accountId);
    this.window.contentView.addChildView(view);
    view.webContents.setZoomFactor(PANEL.zoom);
    this.layout();
    return true;
  }

  /** 该账号当前是否以悬浮面板形式挂着(挂上了才有真实布局,调用方据此决定是否还需要视口覆盖)。 */
  isPanelled(accountId: string): boolean {
    return this.panels.includes(accountId);
  }

  /** 撤下悬浮面板。若期间它被 show() 亮到了前台,留着不动 —— 那是用户要看的。 */
  panelDetach(accountId: string): void {
    const index = this.panels.indexOf(accountId);
    if (index >= 0) this.panels.splice(index, 1);
    if (this.visibleId === accountId) return;
    const view = this.views.get(accountId);
    if (view) view.webContents.setZoomFactor(1);
    this.detachView(accountId);
    this.layout();
  }

  /** 从前台撤下:仍在面板列表里的沉回面板形态(任务还在跑,画面不能断),否则整个移出窗口。 */
  private demote(accountId: string): void {
    if (this.panels.includes(accountId)) {
      this.panelAttach(accountId);
      return;
    }
    this.detachView(accountId);
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
    if (!this.window || this.window.isDestroyed()) {
      return;
    }
    const [width, height] = this.window.getContentSize();

    // 前台全屏视图:铺满内容区(顶部留出渲染层自己画的工具条)。
    const visible = this.visibleId ? this.views.get(this.visibleId) : null;
    if (visible) {
      visible.setBounds({
        x: 0,
        y: EMBED_HEADER_HEIGHT,
        width,
        height: Math.max(0, height - EMBED_HEADER_HEIGHT),
      });
    }

    // 悬浮面板:右下角卡片堆,后挂的在上、每层向上错开一点,好看出同时有几路在跑。
    // 面板必须**整块落在可视区内** —— 实测挂进窗口但 bounds 移出屏幕的视图视口是 0×0,
    // 布局与命中测试双双失效,可信输入就白费了。所以错开量有上限,不让底层被推出窗口。
    const maxStack = Math.max(1, Math.floor((height - PANEL.height - PANEL.margin * 2) / PANEL.stackOffset) + 1);
    this.panels.forEach((accountId, index) => {
      if (accountId === this.visibleId) return; // 已在前台全屏,别再按面板摆
      const view = this.views.get(accountId);
      if (!view) return;
      const depth = Math.min(this.panels.length - 1 - index, maxStack - 1);
      view.setBounds({
        x: Math.max(0, width - PANEL.width - PANEL.margin),
        y: Math.max(EMBED_HEADER_HEIGHT, height - PANEL.height - PANEL.margin - depth * PANEL.stackOffset),
        width: PANEL.width,
        height: PANEL.height,
      });
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

// ---- 共享实例 ------------------------------------------------------------
//
// 发布执行器与浏览器(RPA/智能体)执行器**共用同一个** AccountViewManager:同一套内嵌视图、同一套
// 面板叠放、同一套可信输入。此前两者各自持有一个管理器,RPA 那个还是离屏 BrowserWindow,于是同类
// 问题要在两处分别解决(见已删除的 browserSessions.ts)。
let shared: AccountViewManager | null = null;

export function createSharedViews(onViewChanged?: (state: ViewState) => void): AccountViewManager {
  shared = new AccountViewManager(onViewChanged);
  return shared;
}

/** 当前共享实例;尚未创建(发布执行器还没启动)时为 null。 */
export function sharedViews(): AccountViewManager | null {
  return shared;
}

export function destroySharedViews(): void {
  shared?.destroyAll();
  shared = null;
}
