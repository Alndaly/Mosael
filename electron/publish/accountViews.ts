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


/**
 * 后台任务的「悬浮面板」几何。
 *
 * 卡片外廓 384×244,里面嵌一个内缩 4px、让出 26px 标题条的原生视图;缩放按「视图宽 / layoutWidth」
 * 反算,于是页面**布局视口恒为 1280 宽**,平台页面按桌面版排版,显示只占右下角一小块。这不是美观
 * 取舍,是必要条件:面板若不缩放地做成 384 宽,B 站会渲染窄屏版布局,选择器与整个流程都会变。
 *
 * 为什么要挂进窗口而不是留在后台:只有**参与合成**的视图才有真实布局和可用的命中测试 —— 挂上去
 * 之后真实指针输入(isTrusted=true)才生效,同时画面也是真的,不必再靠截图镜像。实测三个面板
 * 叠放(后加的压住先加的)时,被完全遮挡的那个照样有 1280×800 视口、照样能被可信点击命中。
 */
const PANEL = {
  /** 卡片(含标题条与边框)的外廓尺寸。 */
  width: 384,
  height: 244,
  /** React 在卡片顶部画的标题条高度 —— 原生视图从这条下面开始。 */
  header: 26,
  /** 视图四周相对卡片内缩。卡片圆角 R 时,内缩需 ≥ 0.293R 才不让视图的直角戳出圆弧;
   *  R=12 → 3.5px,取 4px。原生 View 没有 setBorderRadius(Electron 32 只有 setBackgroundColor /
   *  setBounds / setVisible),圆角与阴影只能由渲染层画在视图**下方**(子视图永远盖在宿主页面之上)。 */
  inset: 4,
  /** 卡片圆角,渲染层与这里必须一致(经 IPC 下发,见 emitPanels)。 */
  radius: 12,
  margin: 16,
  stackOffset: 22,
  /** 页面要按这个宽度布局(桌面版)。缩放由「视图实际宽度 / 这个值」反算,而不是写死 0.3 —— 卡片
   *  尺寸一改,写死的比例就会让布局视口偏掉。 */
  layoutWidth: 1280,
} as const;

/**
 * 同时挂载的面板上限。挂载的视图是真在合成的页面,不是免费的 —— 智能体可能开很多路会话,全挂上去
 * 既吃 GPU 也把卡片堆推出窗口。超出上限的视图不挂载:它照样能跑(RPA 的动作走的是 DOM 事件,不
 * 依赖布局与命中测试),只是没有画面、也用不上可信输入。
 */
const MAX_PANELS = 4;

/** 面板最小尺寸:再小就既看不清、也让标题条上的手柄挤成一团。 */
const PANEL_MIN = { width: 240, height: 160 } as const;
/** 空闲清扫的检查间隔。 */
const IDLE_SWEEP_MS = 5_000;
/** 用户拖动/缩放后的面板几何存这儿,重启后接着用。 */
const LAYOUT_FILE = "panel-layout.json";

const platformUserAgent = (userAgent: string): string => {
  return userAgent.replace(/\sElectron\/[\d.]+/i, "");
};

/** 悬浮卡片的几何,下发给渲染层去画圆角/阴影/标题条(原生 View 画不了这些)。 */
export interface PanelCard {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  header: number;
  radius: number;
}

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
  /**
   * 用户拖动/缩放后的面板几何。x/y 为 null 表示「贴右下角」(默认),拖过之后就记住绝对位置。
   * 卡片堆仍从这个锚点向上错开。
   */
  private panelLayout: { x: number | null; y: number | null; width: number; height: number } = {
    x: null,
    y: null,
    width: PANEL.width,
    height: PANEL.height,
  };
  /**
   * 自动关闭:面板 → 允许空闲多久(毫秒)。
   *
   * **不能用「页面没动」当空闲判据** —— 发布任务在 waitResult 里合理地静默十几分钟(B 站在后台
   * 转码审核),按页面活动扫会把还在跑的任务的面板收掉。所以空闲由**所有者主动 touch** 表达:
   * 发布任务不设超时(它在 finally 里显式撤面板),RPA 会话设超时(智能体可能永远不发 close)。
   */
  private panelIdleMs = new Map<string, number>();
  private panelTouchedAt = new Map<string, number>();
  private idleTimer: ReturnType<typeof setInterval> | null = null;
  private window: BaseWindow | null = null;
  private visibleId: string | null = null;
  private nameOf: (accountId: string) => string | null = () => null;

  constructor(
    private readonly onViewChanged: (state: ViewState) => void = noop,
    private readonly onPanelsChanged: (cards: PanelCard[]) => void = () => undefined,
  ) {}

  attachWindow(window: BaseWindow, nameResolver: (accountId: string) => string | null): void {
    this.window = window;
    this.nameOf = nameResolver;
    window.on("resize", () => this.layout());
    this.loadPanelLayout();
    if (!this.idleTimer) this.idleTimer = setInterval(() => this.sweepIdlePanels(), IDLE_SWEEP_MS);
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
    // 面板模式把 zoomFactor 压到不到三成;亮到前台必须还原成 1,否则整页缩成一小块。
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
  panelAttach(accountId: string, opts?: { idleMs?: number }): boolean {
    if (!this.window || this.window.isDestroyed() || this.visibleId === accountId) {
      return false;
    }
    if (!this.panels.includes(accountId)) {
      if (this.panels.length >= MAX_PANELS) return false; // 见 MAX_PANELS:超额不挂,但任务照跑
      this.panels.push(accountId);
    }
    if (opts?.idleMs) this.panelIdleMs.set(accountId, opts.idleMs);
    this.panelTouchedAt.set(accountId, Date.now());
    const { view } = this.ensure(accountId);
    this.window.contentView.addChildView(view);
    view.webContents.setZoomFactor(this.panelZoom());
    this.layout();
    return true;
  }

  /**
   * 用户拖动/缩放面板后调这个。x/y 传绝对坐标(卡片左上角),不传则保持「贴右下角」。
   * 会夹到窗口内并尊重最小尺寸,然后落盘,重启后接着用。
   */
  setPanelLayout(patch: { x?: number; y?: number; width?: number; height?: number }): void {
    const next = { ...this.panelLayout };
    if (patch.width !== undefined) next.width = Math.max(PANEL_MIN.width, Math.round(patch.width));
    if (patch.height !== undefined) next.height = Math.max(PANEL_MIN.height, Math.round(patch.height));
    if (patch.x !== undefined) next.x = Math.round(patch.x);
    if (patch.y !== undefined) next.y = Math.round(patch.y);

    if (this.window && !this.window.isDestroyed()) {
      const [w, h] = this.window.getContentSize();
      next.width = Math.min(next.width, w - PANEL.margin * 2);
      next.height = Math.min(next.height, h - EMBED_HEADER_HEIGHT - PANEL.margin);
      if (next.x !== null) next.x = Math.min(Math.max(0, next.x), Math.max(0, w - next.width));
      if (next.y !== null) {
        next.y = Math.min(Math.max(EMBED_HEADER_HEIGHT, next.y), Math.max(EMBED_HEADER_HEIGHT, h - next.height));
      }
    }
    this.panelLayout = next;
    // 尺寸变了 → 缩放要跟着变(布局视口必须恒为 layoutWidth),所以每块面板都补一次。
    for (const id of this.panels) this.applyPanelZoom(id);
    this.layout();
    this.savePanelLayout();
  }

  /** 面板被用到了 —— 刷新空闲计时(自动关闭的判据由所有者主动 touch 表达,见 panelIdleMs)。 */
  touchPanel(accountId: string): void {
    if (this.panels.includes(accountId)) this.panelTouchedAt.set(accountId, Date.now());
  }

  /** 空闲超时的面板自动撤下(只对声明了 idleMs 的,比如 RPA 会话 —— 智能体可能永远不发 close)。 */
  private sweepIdlePanels(): void {
    const now = Date.now();
    for (const accountId of [...this.panels]) {
      const idleMs = this.panelIdleMs.get(accountId);
      if (!idleMs) continue; // 没声明超时的(发布任务)由所有者自己撤
      const touchedAt = this.panelTouchedAt.get(accountId) ?? now;
      if (now - touchedAt > idleMs) {
        console.info("[open-studio:view] panel auto-closed (idle)", { accountId, idleMs });
        this.panelDetach(accountId);
      }
    }
  }

  private layoutFilePath(): string {
    return path.join(app.getPath("userData"), LAYOUT_FILE);
  }

  private loadPanelLayout(): void {
    try {
      const raw = JSON.parse(fs.readFileSync(this.layoutFilePath(), "utf8")) as Partial<typeof this.panelLayout>;
      // 只接受数值/null,并且照常过一遍 setPanelLayout 的夹取 —— 窗口尺寸可能比上次小。
      this.setPanelLayout({
        x: typeof raw.x === "number" ? raw.x : undefined,
        y: typeof raw.y === "number" ? raw.y : undefined,
        width: typeof raw.width === "number" ? raw.width : undefined,
        height: typeof raw.height === "number" ? raw.height : undefined,
      });
    } catch {
      /* 没存过 / 文件坏了:用默认的贴右下角 */
    }
  }

  private savePanelLayout(): void {
    try {
      fs.writeFileSync(this.layoutFilePath(), JSON.stringify(this.panelLayout));
    } catch {
      /* 落盘失败不影响使用,下次重启回到默认位置而已 */
    }
  }

  /** 该账号当前是否以悬浮面板形式挂着(挂上了才有真实布局,调用方据此决定是否还需要视口覆盖)。 */
  isPanelled(accountId: string): boolean {
    return this.panels.includes(accountId);
  }

  /** 面板模式的缩放:视图实际宽度 / 期望布局宽度。用户缩放面板后这个值随之变化,
   *  所以布局视口恒为 layoutWidth —— 平台页面永远按桌面版排版,不随面板大小掉进窄屏分支。 */
  private panelZoom(): number {
    return (this.panelLayout.width - PANEL.inset * 2) / PANEL.layoutWidth;
  }

  /** 把面板缩放重新设一遍。同源缩放策略下每次导航都要补,见 ensure() 里 sync 的说明。 */
  private applyPanelZoom(accountId: string): void {
    if (this.visibleId === accountId || !this.panels.includes(accountId)) return;
    const view = this.views.get(accountId);
    if (!view || view.webContents.isDestroyed()) return;
    const zoom = this.panelZoom();
    if (Math.abs(view.webContents.getZoomFactor() - zoom) > 1e-6) {
      view.webContents.setZoomFactor(zoom);
    }
  }

  /** 撤下悬浮面板。若期间它被 show() 亮到了前台,留着不动 —— 那是用户要看的。 */
  panelDetach(accountId: string): void {
    const index = this.panels.indexOf(accountId);
    if (index >= 0) this.panels.splice(index, 1);
    this.panelIdleMs.delete(accountId);
    this.panelTouchedAt.delete(accountId);
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
    if (this.idleTimer) {
      clearInterval(this.idleTimer);
      this.idleTimer = null;
    }
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
        // 导航后必须**重新**设一次面板缩放。Chromium 的缩放策略是 same-origin(Electron 文档原话:
        // "The zoom policy at the Chromium level is same-origin"),所以挂面板时设的 0.3 只对当时那个
        // 域名有效 —— 一 goto 到新域名就回到 1,页面按 1:1 渲染再被 384×240 裁掉,只能看见左上角一块。
        // 线上就是这么表现的(百度导航栏字号正常、内容被切)。
        this.applyPanelZoom(accountId);
      };
      view.webContents.on("did-navigate", sync);
      view.webContents.on("did-navigate-in-page", sync);
      view.webContents.on("did-start-loading", sync);
      view.webContents.on("did-stop-loading", sync);
      view.webContents.on("did-finish-load", sync);
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
    const { width: cardW, height: cardH } = this.panelLayout;
    const anchorX = this.panelLayout.x ?? Math.max(0, width - cardW - PANEL.margin);
    const anchorY = this.panelLayout.y ?? Math.max(EMBED_HEADER_HEIGHT, height - cardH - PANEL.margin);
    const maxStack = Math.max(1, Math.floor((anchorY - EMBED_HEADER_HEIGHT) / PANEL.stackOffset) + 1);
    const cards: PanelCard[] = [];
    this.panels.forEach((accountId, index) => {
      if (accountId === this.visibleId) return; // 已在前台全屏,别再按面板摆
      const view = this.views.get(accountId);
      if (!view) return;
      const depth = Math.min(this.panels.length - 1 - index, maxStack - 1);
      // 卡片外廓:渲染层照这个矩形画圆角、边框、阴影和标题条。
      const card = {
        id: accountId,
        x: anchorX,
        y: Math.max(EMBED_HEADER_HEIGHT, anchorY - depth * PANEL.stackOffset),
        width: cardW,
        height: cardH,
        header: PANEL.header,
        radius: PANEL.radius,
      };
      cards.push(card);
      // 原生视图嵌在卡片里:让出标题条,四周内缩,于是卡片的圆角边框在视图外侧露出来。
      view.setBounds({
        x: card.x + PANEL.inset,
        y: card.y + PANEL.header,
        width: cardW - PANEL.inset * 2,
        height: cardH - PANEL.header - PANEL.inset,
      });
    });
    this.onPanelsChanged(cards);
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

export function createSharedViews(
  onViewChanged?: (state: ViewState) => void,
  onPanelsChanged?: (cards: PanelCard[]) => void,
): AccountViewManager {
  shared = new AccountViewManager(onViewChanged, onPanelsChanged);
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
