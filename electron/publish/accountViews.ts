import { app, screen, session, WebContentsView, type BaseWindow } from "electron";
import fs from "node:fs";
import path from "node:path";
import { EMBED_HEADER_HEIGHT, type PageSummary, type ViewState } from "./types";
import { DownloadRouter, type DownloadNotice } from "./downloads";
import { MediaRecorder } from "./mediaRecorder";
import { PageDriver } from "./pageDriver";
import { MAX_PAGES, PageList, type PageMatch } from "./pageList";
import { panelMediaScript } from "./panelAudio";
import {
  DEFAULT_PANEL_LAYOUT,
  PANEL,
  fitPanelLayout,
  movePanel,
  panelStack,
  resizePanel,
  type PanelArea,
  type PanelHandle,
  type PanelLayout,
  type PanelRect,
} from "./panelGeometry";
import { PanelHover } from "./panelHover";

/* eslint-disable @typescript-eslint/no-require-imports */
const { handleAccountSelection: bindWebauthnAccountSelection } =
  require("../webauthn.cjs") as { handleAccountSelection: (partition: string) => void };

const noop = (): void => undefined;
// 账号视图 preload:注入「← 返回 Mosael」悬浮按钮(见 electron/account-view-preload.cjs)。运行时
// 该文件与打包出的 publish.bundle.cjs 同在 electron/ 下,故按 __dirname 定位。
const ACCOUNT_VIEW_PRELOAD = path.join(__dirname, "account-view-preload.cjs");

/** 发布账号登录分区前缀(完整名 persist:<PARTITION_PREFIX>-<accountId>)。
 *  必须与后端 app/core/db.py 的 PARTITION_PREFIX 一致 —— 两边拼的是同一个磁盘目录。
 *  由 contracts/shared-constants.json 钉住。 */
export const PARTITION_PREFIX = "mosael";

/** 截图时临时挂到窗口外面的页面离窗口左边多远(DIP)。 */
const OFF_WINDOW_GAP = 64;

/** 截图要的那一页已经没了(会话关了、页面关了)。 */
export class PageGoneError extends Error {
  constructor(viewId: string, pageId: string | null) {
    super(`page gone: ${viewId}${pageId ? ` / ${pageId}` : ""}`);
    this.name = "PageGoneError";
  }
}

/**
 * 刚挂上的页面等它按新视口排好版、画完一帧(最多等一秒;等不到就照样往下截,不卡住这一步)。
 * 从没挂过的页面挂上之前视口是 0×0。
 */
async function settleLayout(wc: Electron.WebContents): Promise<void> {
  const deadline = Date.now() + 1_000;
  while (Date.now() < deadline) {
    const width = Number(await wc.executeJavaScript("innerWidth").catch(() => 0));
    if (width > 0) break;
    await new Promise((resolve) => setTimeout(resolve, 16));
  }
  await wc
    .executeJavaScript("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => done(true))))")
    .catch(() => undefined);
}

/** 连按两次 Esc 判定为「退出内嵌浏览器」的时间窗(见 ensure() 里的 before-input-event)。 */
const DOUBLE_ESCAPE_MS = 700;

/** 焦点在这一帧的可编辑元素上吗(输入框、文本框、下拉、contenteditable)。 */
const TYPING_PROBE = `(() => {
  if (!document.hasFocus()) return false;
  const el = document.activeElement;
  if (!el) return false;
  if (el.isContentEditable || el.tagName === "TEXTAREA" || el.tagName === "SELECT") return true;
  if (el.tagName !== "INPUT") return false;
  return !/^(button|submit|reset|checkbox|radio|image|file|range|color)$/i.test(el.type || "");
})()`;

/** 用户正在网页里打字吗:任何一帧(含 iframe)里焦点在可编辑元素上就算。问不到的帧当作没在打字。 */
async function typingIn(wc: Electron.WebContents): Promise<boolean> {
  const root = wc.mainFrame;
  const frames = [root, ...(root.framesInSubtree ?? [])];
  const answers = await Promise.all(
    frames.map((frame) => Promise.resolve(frame.executeJavaScript(TYPING_PROBE)).then((value) => value === true, () => false)),
  );
  return answers.some(Boolean);
}

/**
 * 同时挂载的面板上限。挂载的视图是真在合成的页面,不是免费的 —— 智能体可能开很多路会话,全挂上去
 * 既吃 GPU 也把卡片堆推出窗口。超出上限的视图不挂载:它照样能跑(RPA 的动作走的是 DOM 事件,不
 * 依赖布局与命中测试),只是没有画面、也用不上可信输入。
 */
const MAX_PANELS = 4;

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
  /** Electron 层的真实静音状态；标题条据此画开关。 */
  muted: boolean;
  /** 指针正停在这张卡片的网页上(渲染层看不见那一块,见 PanelHover)。卡片外壳据此亮出缩放手柄。 */
  hovered: boolean;
  /** 这个会话开着几个页面、当前是第几个(从 1 起)。标题条上紧凑地标一下「2/3」。 */
  pages: number;
  page: number;
}

/** 会话里的一个页面:一个活着的网页视图和它的驱动。只有当前页挂在窗口上,别的在后台活着。 */
interface PageTab {
  view: WebContentsView;
  driver: PageDriver;
  favicon: string;
}

const tabId = (tab: PageTab): string => String(tab.view.webContents.id);

/**
 * 渲染层对面板几何的一次改动:要么拖标题条挪位置,要么拖某个手柄缩放。缩放给的是指针要的矩形
 * (不带约束),比例、上下限与窗口边界由 panelGeometry 定。
 */
/**
 * 前台视图为什么暂时不在原处:框选截图(渲染层在原处铺冻结的画面让人拖框)、页面列表在网页那张画面上展开 /
 * 收起 / 临时展开(`cover`)。两件事可能同时在 —— 哪一件还要它让开,它就让开。
 *
 * 两种让法不一样:框选时**藏起来**;`cover` 是**挪到窗口外面**、照常显示 —— 网页一直在出帧,揭开时回来的就是
 * 它此刻的样子。藏起来的视图揭开那一下可能先闪一帧藏之前的画面。
 */
export type ForegroundHideReason = "region" | "cover";

/** 前台网页此刻的画面和它在窗口里的位置(CSS 像素):渲染层照这个把画面铺回原处。 */
export interface ForegroundSnapshot {
  frame: string;
  bounds: { x: number; y: number; width: number; height: number };
}

export type PanelLayoutChange = { x: number; y: number } | ({ handle: PanelHandle } & PanelRect);

/**
 * Owns one embedded WebContentsView per account. Each view uses a persistent
 * session partition (`persist:mosael-<id>`) so cookies / localStorage are isolated
 * and survive restarts — this replaces the old Playwright per-account profile
 * directory. The view is laid into the host BaseWindow below a fixed header
 * strip that the renderer keeps clear for its own controls.
 */
export class AccountViewManager {
  /**
   * 每个视图(会话)**当前页**的网页视图与驱动。一个会话可以开好几个页面(新窗口、target=_blank、
   * 用户「新建页面」都进同一个会话的页面列表,见 tabs);这两张表永远指着当前那一页 —— 顶栏工具、
   * 自动化的下一步、截图都作用在它上面,不用每一处都去问「是哪一页」。
   */
  private views = new Map<string, WebContentsView>();
  private drivers = new Map<string, PageDriver>();
  /** 每个会话的全部页面(先后次序、哪个是当前页,见 pageList)。 */
  private tabs = new Map<string, PageList<PageTab>>();
  private appliedProxy = new Map<string, string | null>();
  // 泛化:非发布账号的视图(浏览器池通用档案)显式登记其分区与显示名;发布账号不登记,
  // 沿用 persist:mosael-<accountId>。这样同一套内嵌视图既服务发布登录、也服务池档案登录。
  private partitions = new Map<string, string>();
  private names = new Map<string, string>();
  // 正在以悬浮面板形式挂载的账号,按挂载顺序 —— 决定叠放次序(后挂的在上)。
  private panels: string[] = [];
  /** 用户明确允许出声的悬浮面板。未挂载/已关闭的视图永远不在这里。 */
  private audiblePanels = new Set<string>();
  /**
   * 用户拖动/缩放后的面板几何(见 PanelLayout)。卡片堆最上面那张落在这里,其余从它向上错开。
   */
  private panelLayout: PanelLayout = DEFAULT_PANEL_LAYOUT;
  /** 指针停在哪些面板的网页上。状态一变就重排一次,把 hovered 随卡片下发。 */
  private hover = new PanelHover({
    pointerInside: (id) => this.pointerOverView(id),
    onChange: () => this.layout(),
  });
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
  /**
   * 前台视图右侧让出多少像素给顶栏页面工具的侧栏(视频清单、图片网格)。侧栏是渲染层的 DOM,
   * 而原生视图永远盖在 DOM 上面 —— 不让出这一块,侧栏就画在网页底下、谁也看不见。让出而不是
   * 盖住:网页照常排版、照常能点,只是窄一点。换前台视图、收起视图时归零。
   */
  private shellInsetRight = 0;
  /**
   * 前台视图暂时藏起来的原因(见 ForegroundHideReason):渲染层在原处铺一张冻结的画面,在上面画框、
   * 盖列表(原生视图盖在一切 DOM 上)。只藏不摘 —— 页面不重排、不暂停,用完原样亮回来。
   */
  private foregroundHiddenFor = new Set<ForegroundHideReason>();
  /** 最后拿着焦点的那个(见 focusTarget)。 */
  private lastFocused: Electron.WebContents | null = null;
  /** 前台视图收到过的媒体响应(「下载页面里的视频」要用,见 mediaRecorder)。 */
  readonly media = new MediaRecorder();
  private downloadRouter: DownloadRouter | null = null;
  /**
   * 前台视图左侧让出多少像素给页面列表(渲染层的 DOM,原生视图盖不住它就得让开)。列表挂着时由渲染层
   * 报来,收起成图标条时变窄。
   */
  private shellInsetLeft = 0;
  /** 最近一次因为页面开满了而拦下新窗口的时刻;随状态下发,渲染层据此提示一句。 */
  private pageLimitHitAt = 0;

  constructor(
    private readonly onViewChanged: (state: ViewState) => void = noop,
    private readonly onPanelsChanged: (cards: PanelCard[]) => void = () => undefined,
    private readonly onDownload: (notice: DownloadNotice) => void = () => undefined,
  ) {}

  /**
   * 视图里的下载不弹保存框、直接进素材库(见 downloads.ts)。第一次建视图时才建:临时目录在 userData 下,
   * 建的时候清一遍上次没交出去的。
   */
  get downloads(): DownloadRouter {
    this.downloadRouter ??= new DownloadRouter(
      (wc) => this.viewIdOf(wc),
      (notice) => this.onDownload(notice),
      path.join(app.getPath("userData"), "web-downloads"),
    );
    return this.downloadRouter;
  }

  /** 这个页面是哪个视图(会话)的 —— 会话里的每一页都算;不是我们的页面返回 null。 */
  private viewIdOf(wc: Electron.WebContents): string | null {
    for (const [id, list] of this.tabs) {
      if (list.list().some(({ item }) => this.alive(item.view) && item.view.webContents.id === wc.id)) return id;
    }
    return null;
  }

  attachWindow(window: BaseWindow, nameResolver: (accountId: string) => string | null): void {
    this.window = window;
    this.nameOf = nameResolver;
    const host = this.hostWebContents();
    host?.on("focus", () => {
      this.lastFocused = host;
    });
    window.on("resize", () => this.fitPanelsToWindow());
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
    // 一次请求解出多把可发现凭据时由我们来选。**不接这个监听器,请求会被直接取消。**
    bindWebauthnAccountSelection(partition);
    await accountSession.setProxy({
      mode: normalizedProxy ? "fixed_servers" : "direct",
      proxyRules: normalizedProxy ?? undefined,
    });
    this.appliedProxy.set(partition, normalizedProxy);
  }

  /** 通用:在给定分区开一个内嵌视图、亮出并导航到 url —— 供「浏览器池」通用档案登录复用**同一套**
   *  内嵌视图(与发布账号登录一致:同容器、同「返回 Mosael」、同顶栏工具条),不弹外部系统窗。
   *  viewId 用分区名(唯一,且不与发布 accountId 冲突)。 */
  /**
   * `resume`:这个视图还开着页面的话就原样亮出来,不导航 —— 通用档案是一个一直保留的浏览器,
   * 「打开」要回到上次停下的那一页,而不是每次跳回第一次输入的地址。视图已经没了(重启过)
   * 才按 `url` 开,调用方给的是上次关掉时记下的地址。
   */
  async openView(opts: { viewId: string; partition: string; name?: string; url: string; proxy?: string | null; resume?: boolean }): Promise<void> {
    // 池档案的分区名直接来自数据库,不经 partitionFor,故这里也要触发一次遗留目录迁移。
    this.partitions.set(opts.viewId, opts.partition);
    if (opts.name) this.names.set(opts.viewId, opts.name);
    const normalizedProxy = opts.proxy?.trim() || null;
    if (this.appliedProxy.get(opts.partition) !== normalizedProxy) {
      const viewSession = session.fromPartition(opts.partition);
      bindWebauthnAccountSelection(opts.partition);
      await viewSession.setProxy({
        mode: normalizedProxy ? "fixed_servers" : "direct",
        proxyRules: normalizedProxy ?? undefined,
      });
      this.appliedProxy.set(opts.partition, normalizedProxy);
    }
    const existing = this.views.get(opts.viewId);
    const current = this.alive(existing) ? existing.webContents.getURL() : "";
    const { view } = this.ensure(opts.viewId);
    this.show(opts.viewId);
    if (opts.resume && current && current !== "about:blank") return;
    const url = normalizeAddress(opts.url);
    if (url) void view.webContents.loadURL(url);
  }

  /**
   * 登记一个「非发布账号」的会话视图:显式指定分区,建好视图与驱动,但**不亮出来**。
   *
   * 供 RPA / 智能体会话复用同一套内嵌视图(此前它们自己起离屏 BrowserWindow —— 见已删除的
   * browserSessions.ts)。分区照旧严格隔离:ephemeral-*(内存态)/ persist:rpa-* 与发布的
   * persist:mosael-* 互不相干。
   */
  registerSession(viewId: string, partition: string): PageDriver {
    this.partitions.set(viewId, partition);
    return this.ensure(viewId).driver;
  }

  /**
   * 这个视图的页面是不是还在等主文档的响应 —— 点了一个链接、还不知道它是新页面还是一个下载。
   * 自动化收下载时据此多等一会儿(见 actionDownloads)。
   */
  awaitingResponse(viewId: string): boolean {
    const view = this.views.get(viewId);
    return this.alive(view) && view.webContents.isWaitingForResponse();
  }

  /**
   * 拿会话里的一页去截图(`pageId` 为 null 是当前页)—— **不管它挂没挂在窗口上**。
   *
   * 没挂在窗口上的页面 Chromium 不给它排版出帧:从没挂过的(面板满了没挂上的第 5 个会话、后台打开的页面)视口
   * 是 0×0、capturePage 给空图,CDP 截图一直等不到;挂过又摘下来的(切到后台的页面)CDP 也等不到。实测见
   * actionCapture 的说明。所以截图的时候临时把它挂上窗口,但整块放在窗口**外面**(负坐标,窗口再怎么拉大也露
   * 不出来)、先定位置再挂 —— 用户看不见、不闪;按它本来会有的布局宽度、缩放 1 排版(这个会话当前页挂着就
   * 照它的 CSS 视口,否则照面板的桌面版宽度),截完摘下、大小和缩放还原。截的途中用户正好切到了这一页,就让它
   * 留在原处。已经挂在窗口上的页面原地截,不动它。
   */
  async withPageOnSurface<T>(viewId: string, pageId: string | null, shoot: (wc: Electron.WebContents) => Promise<T>): Promise<T> {
    const list = this.tabs.get(viewId);
    const tab = pageId === null ? list?.current()?.item : list?.get(pageId);
    if (!tab || !this.alive(tab.view)) throw new PageGoneError(viewId, pageId);
    const { view } = tab;
    if (!this.window || this.window.isDestroyed() || this.onWindow(view)) return shoot(view.webContents);
    const surface = this.layoutSurface(viewId);
    const before = { bounds: view.getBounds(), zoom: view.webContents.getZoomFactor() };
    view.setBounds({ x: -(surface.width + OFF_WINDOW_GAP), y: 0, width: surface.width, height: surface.height });
    view.webContents.setZoomFactor(1);
    this.window.contentView.addChildView(view);
    try {
      await settleLayout(view.webContents);
      return await shoot(view.webContents);
    } finally {
      // 截的途中被切成了前台 / 面板上的当前页:那是用户要看的,别摘。
      const nowShown = this.views.get(viewId) === view && (this.visibleId === viewId || this.panels.includes(viewId));
      if (!nowShown && this.alive(view)) {
        this.detachChild(view);
        view.setBounds(before.bounds);
        view.webContents.setZoomFactor(before.zoom);
      }
    }
  }

  /** 这个视图此刻挂在窗口上没有。 */
  private onWindow(view: WebContentsView): boolean {
    return Boolean(this.window && !this.window.isDestroyed() && this.window.contentView.children.includes(view));
  }

  /**
   * 会话的页面按多大的视口排版(DIP,缩放 1):当前页挂着就照它的 CSS 视口(视图大小 / 缩放),否则照面板 ——
   * 面板的网页区除以面板缩放,就是平台页面那套桌面版布局宽度。
   */
  private layoutSurface(viewId: string): { width: number; height: number } {
    const current = this.views.get(viewId);
    if (this.alive(current) && this.onWindow(current)) {
      const bounds = current.getBounds();
      const zoom = current.webContents.getZoomFactor() || 1;
      return { width: Math.round(bounds.width / zoom), height: Math.round(bounds.height / zoom) };
    }
    const area = this.panelArea() ?? { width: 1440, height: 900 };
    const page = panelStack(this.panelLayout, area, 1).page;
    const zoom = this.panelZoom();
    return { width: Math.round(page.width / zoom), height: Math.round(page.height / zoom) };
  }

  private detachChild(view: WebContentsView): void {
    if (!this.window || this.window.isDestroyed()) return;
    try {
      this.window.contentView.removeChildView(view);
    } catch {
      // 已经摘掉了
    }
  }

  /** 已建好的驱动(不新建)。 */
  existingDriver(viewId: string): PageDriver | null {
    return this.drivers.get(viewId) ?? null;
  }

  /** 这个会话当前那一页的网页(不新建;没了是 null)—— 要在它每次载入之后做点事的(ComfyUI 的桥、操控方式)挂监听用。 */
  currentContents(viewId: string): Electron.WebContents | null {
    const view = this.views.get(viewId);
    return this.alive(view) ? view.webContents : null;
  }

  /**
   * 这个视图还能用吗 —— **`views` 里有没有 ≠ 它还活着**。
   *
   * WebContents 可以在我们的 destroy() 之外没掉:渲染进程崩溃、页面自己 window.close()、系统
   * 回收。此后 `view.webContents` 直接是 undefined,于是任何一处 `view.webContents.xxx` 都会抛
   * 「Cannot read properties of undefined」——线上就是点「去登录」时报 setZoomFactor 那一条。
   * 所有拿到视图之后要用它的地方,都得先过这一关。
   */
  private alive(view: WebContentsView | undefined | null): view is WebContentsView {
    return Boolean(view?.webContents && !view.webContents.isDestroyed());
  }

  /**
   * 视图没了之后的收尾:从窗口摘掉、忘掉它,并且**绝不让 visibleId 指着一个尸体**。
   *
   * visibleId 指着已经没了的视图,就是那条「登录完顶部 header 还赖着不走」:emit() 只看
   * `visibleId !== null` 就报 visible=true,渲染层照着画工具条,而它底下已经什么都没有了。
   * 幂等 —— destroy() 主动关闭时会再触发一次 webContents 的 destroyed 事件,两条路进来结果一样。
   */
  private forget(accountId: string): void {
    this.detachView(accountId);
    // 会话里别的页面本来就没挂在窗口上;这里只清账本(关掉它们是 destroy 的事)。
    this.tabs.delete(accountId);
    const index = this.panels.indexOf(accountId);
    if (index >= 0) this.panels.splice(index, 1);
    this.panelIdleMs.delete(accountId);
    this.panelTouchedAt.delete(accountId);
    this.audiblePanels.delete(accountId);
    this.hover.drop(accountId);
    this.views.delete(accountId);
    this.drivers.delete(accountId);
    if (this.visibleId === accountId) {
      this.visibleId = null;
      this.syncAudio();
      this.emit();
    }
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
    this.hover.drop(accountId); // 亮到前台就不再是面板,手柄不该因为它亮着
    if (this.visibleId !== accountId) this.resetShell();
    this.visibleId = accountId;
    // 从亮到前台这一刻起记媒体响应:视频地址往往只在页面加载时出现一次。
    this.media.watch(view.webContents.session);
    this.layout();
    // Re-adding the same View is the current View API's z-order operation:
    // Electron reorders it to the topmost child of the window content view.
    this.window.contentView.addChildView(view);
    // 进了内嵌浏览器,键盘就在网页里(不然打的字还落在 Mosael 那边看不见的地方)。
    view.webContents.focus();
    console.info("[mosael:view] shown", {
      accountId,
      bounds: view.getBounds(),
      childCount: this.window.contentView.children.length,
      url: view.webContents.getURL(),
    });
    this.syncAudio();
    this.emit();
  }

  /**
   * 前台视图默认出声；悬浮面板只有用户明确打开声音后才出声；隐藏视图永远静音。
   *
   * hide() 只是把视图从窗口摘掉 —— WebContents 还在跑,而且我们特意关掉了 backgroundThrottling,
   * 于是 TikTok 信息流这种自动播放的页面在你回到应用之后还在响。静音走 Electron 这一层而不是往页面
   * 里注 JS:页面改不掉它,SPA 也没法在下一次渲染时把自己恢复出声。
   *
   * 判据只在这一个方法里算,show/hide/panelAttach/panelDetach 都调它 —— 不在四个地方各写一遍
   * 「现在该不该静音」。
   */
  private syncAudio(): void {
    for (const [id, list] of this.tabs) {
      for (const { item } of list.list()) {
        if (!this.alive(item.view)) continue;
        // 后台的页面永远静音:它们看不见,不该在那儿响。
        item.view.webContents.setAudioMuted(!(item.view === this.views.get(id) && this.isAudible(id)));
      }
    }
  }

  private isAudible(accountId: string): boolean {
    return accountId === this.visibleId || (this.panels.includes(accountId) && this.audiblePanels.has(accountId));
  }

  /**
   * 同步网页播放器自身的状态。主 frame 与 iframe 都要做:B 站等页面会把播放器放进子 frame。
   * 失败无所谓,Electron 的硬静音仍是兜底；这里负责恢复被我们暂停或站点默认静音的媒体。
   */
  private syncPageMedia(accountId: string, audible: boolean): void {
    const view = this.views.get(accountId);
    if (!this.alive(view)) return;
    const root = view.webContents.mainFrame;
    const frames = [root, ...root.framesInSubtree];
    const seen = new Set<number>();
    for (const frame of frames) {
      if (seen.has(frame.routingId)) continue;
      seen.add(frame.routingId);
      void frame.executeJavaScript(panelMediaScript(audible), audible).catch(() => undefined);
    }
  }

  /** Hide whatever view is currently shown (returns the window to the React UI). */
  hide(): void {
    if (this.visibleId) {
      // 顺序要紧:先清 visibleId 再 demote。panelAttach 对「正在前台的账号」有早退保护
      // (它不该去动前台视图),先 demote 就会被这条保护挡掉,任务还在跑却收不回面板。
      const previous = this.visibleId;
      this.resetShell();
      this.visibleId = null;
      this.demote(previous);
      this.syncAudio();
      // 收回后仍获用户授权出声的面板继续播放；其余暂停以免隐藏视频继续解码、拉流。
      this.syncPageMedia(previous, this.isAudible(previous));
      // 回到 Mosael:键盘回到 Mosael 的界面(渲染层再把焦点放回打开之前的那个按钮)。
      this.hostWebContents()?.focus();
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
    // 下面的 addChildView 会把这块视图挪到最上层(再加一次同一个 View 就是 View API 的 z 序操作),
    // 所以它在卡片堆里也要排到最上面:已挂着的(比如从前台全屏退回来)先摘出来再放到末尾。次序
    // 对不上的话,最上面那张卡片的外壳底下露出的是别人的网页。
    const index = this.panels.indexOf(accountId);
    if (index >= 0) this.panels.splice(index, 1);
    else if (this.panels.length >= MAX_PANELS) return false; // 见 MAX_PANELS:超额不挂,但任务照跑
    this.panels.push(accountId);
    if (opts?.idleMs) this.panelIdleMs.set(accountId, opts.idleMs);
    this.panelTouchedAt.set(accountId, Date.now());
    const { view } = this.ensure(accountId);
    this.window.contentView.addChildView(view);
    view.webContents.setZoomFactor(this.panelZoom());
    this.syncAudio();
    this.layout();
    return true;
  }

  /**
   * 用户拖动 / 缩放面板后调这个(卡片堆作为一个整体:它们共享锚点与尺寸)。
   *
   * 两种改动,一个动作一个含义:给 x/y 是拖标题条挪位置;带 handle 的是拖某个手柄缩放 —— 尺寸是
   * 一个标量(宽高按页面比例联动,理由见 PanelLayout),手柄只决定**哪个点不动**。规则全在
   * panelGeometry 里:上下限、窗口内约束、锚点。改完落盘,重启后接着用。
   */
  setPanelLayout(change: PanelLayoutChange): void {
    const area = this.panelArea();
    if (!area) return;
    this.applyPanelLayout(
      "handle" in change
        ? resizePanel(change.handle, change, area)
        : movePanel(this.panelLayout, change, area),
    );
    this.savePanelLayout();
  }

  private applyPanelLayout(next: PanelLayout): void {
    this.panelLayout = next;
    // 尺寸变了 → 缩放要跟着变(布局视口必须恒为 layoutWidth),所以每块面板都补一次。
    for (const id of this.panels) this.applyPanelZoom(id);
    this.layout();
  }

  /**
   * 窗口大小变了:面板按同样的上下限与比例重新夹回窗口里(尺寸与位置,和启动时读回存档那一步
   * 是同一个 fitPanelLayout)。此前这里只重排,窗口一缩小,拖到过右下角的面板就半截留在窗口外 ——
   * 而挂在窗口外的视图视口是 0×0,可信输入跟着失效。夹过的结果落盘;没变就不写。
   */
  private fitPanelsToWindow(): void {
    const area = this.panelArea();
    if (!area) return;
    const fitted = fitPanelLayout(this.panelLayout, area);
    const changed = (["x", "y", "width"] as const).some((key) => fitted[key] !== this.panelLayout[key]);
    this.applyPanelLayout(fitted);
    if (changed) this.savePanelLayout();
  }

  /** 窗口内容区 —— 面板几何的边界。窗口没了就没有可摆的地方。 */
  private panelArea(): PanelArea | null {
    if (!this.window || this.window.isDestroyed()) return null;
    const [width, height] = this.window.getContentSize();
    return { width, height };
  }

  /** 系统指针此刻是否在这块面板的网页(原生视图)上。PanelHover 的兜底检查用。 */
  private pointerOverView(accountId: string): boolean {
    const view = this.views.get(accountId);
    if (!this.window || this.window.isDestroyed() || !this.alive(view)) return false;
    const content = this.window.getContentBounds();
    const bounds = view.getBounds();
    const cursor = screen.getCursorScreenPoint();
    const x = cursor.x - content.x;
    const y = cursor.y - content.y;
    return x >= bounds.x && x < bounds.x + bounds.width && y >= bounds.y && y < bounds.y + bounds.height;
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
        console.info("[mosael:view] panel auto-closed (idle)", { accountId, idleMs });
        this.panelDetach(accountId);
      }
    }
  }

  private layoutFilePath(): string {
    return path.join(app.getPath("userData"), LAYOUT_FILE);
  }

  private loadPanelLayout(): void {
    const area = this.panelArea();
    if (!area) return;
    try {
      const { x, y, width } = JSON.parse(fs.readFileSync(this.layoutFilePath(), "utf8")) as Record<string, unknown>;
      // 只认数值;照常过一遍夹取 —— 窗口尺寸可能比上次小。
      const placed = typeof x === "number" && typeof y === "number";
      this.applyPanelLayout(
        fitPanelLayout(
          {
            x: placed ? x : null,
            y: placed ? y : null,
            width: typeof width === "number" ? width : DEFAULT_PANEL_LAYOUT.width,
          },
          area,
        ),
      );
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
    if (!this.alive(view)) return;
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
    this.audiblePanels.delete(accountId);
    this.hover.drop(accountId);
    if (this.visibleId === accountId) return;
    const view = this.views.get(accountId);
    if (this.alive(view)) view.webContents.setZoomFactor(1);
    this.detachView(accountId);
    this.layout();
  }

  /** 用户切换悬浮浏览器声音。只接受仍挂在面板里的 id,避免给隐藏视图留下出声许可。 */
  setPanelMuted(accountId: string, muted: boolean): void {
    if (!this.panels.includes(accountId)) return;
    if (muted) this.audiblePanels.delete(accountId);
    else this.audiblePanels.add(accountId);
    this.syncAudio();
    // 解除 Electron 总静音还不够:网页可能自身 muted/volume=0，或此前被 hide() 暂停。
    if (!muted) this.syncPageMedia(accountId, true);
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

  /** 把当前视图状态再播一次。
   *
   * 状态是**推的**(变化时 emit),渲染层没有办法主动问。于是渲染层一旦重新加载(⌘R、HMR、
   * 崩溃恢复),它的 PublishViewBar 就回到初始的 visible:false —— 而原生视图还好端端盖在窗口上,
   * 表现为「内嵌浏览器还在,顶部工具条没了」。主窗口 did-finish-load 时补播一次即可。
   * 主进程里的全屏状态早就是这么做的(win.webContents.on("did-finish-load", sendFullscreen)),
   * 这一份当时漏了。 */
  republish(): void {
    this.emit();
    this.layout(); // 顺带把悬浮卡片几何也重播一次(layout 末尾会 onPanelsChanged)
  }

  private visibleWebContents(): Electron.WebContents | null {
    const view = this.visibleId ? this.views.get(this.visibleId) : null;
    return this.alive(view) ? view.webContents : null;
  }

  /**
   * 顶栏页面工具作用的对象:**只能是前台那个视图**。渲染层不点名要哪个视图 —— 它看得见的只有
   * 前台这一个,让它点名等于让任何一段渲染层代码都能截后台正在发布的账号页面。
   */
  foreground(): { id: string; webContents: Electron.WebContents; partition: string } | null {
    const wc = this.visibleWebContents();
    if (!wc || !this.visibleId) return null;
    return { id: this.visibleId, webContents: wc, partition: this.partitionFor(this.visibleId) };
  }

  /** 最后拿着焦点的那个:某一页网页,或主窗口(浮层视图抢了焦点时还给它,见 floatLayer)。 */
  focusTarget(): Electron.WebContents | null {
    return this.lastFocused && !this.lastFocused.isDestroyed() ? this.lastFocused : this.hostWebContents();
  }

  /** 键盘交给前台网页(顶栏、页面列表里点完之后,接着打字的就该是网页)。 */
  focusForeground(): void {
    this.visibleWebContents()?.focus();
  }

  /** 主窗口自己的网页(Mosael 的界面)。 */
  private hostWebContents(): Electron.WebContents | null {
    const contents = (this.window as unknown as { webContents?: Electron.WebContents } | null)?.webContents;
    return contents && !contents.isDestroyed() ? contents : null;
  }

  /** 侧栏开合:前台视图右侧让出这么宽(见 shellInsetRight)。 */
  setShellInset(right: number): void {
    const width = this.window && !this.window.isDestroyed() ? this.window.getContentSize()[0] : 0;
    // 至少给网页留一半:侧栏再宽也不能把页面挤没了。
    const next = Math.max(0, Math.min(Math.round(right), Math.floor(width / 2)));
    if (next === this.shellInsetRight) return;
    this.shellInsetRight = next;
    this.layout();
  }

  /** 为某件事让开 / 回到原处;别的事还要它让开就接着让(见 ForegroundHideReason)。 */
  setForegroundHidden(reason: ForegroundHideReason, hidden: boolean): void {
    if (hidden) this.foregroundHiddenFor.add(reason);
    else this.foregroundHiddenFor.delete(reason);
    const view = this.visibleId ? this.views.get(this.visibleId) : null;
    if (this.alive(view)) view.setVisible(!this.foregroundHiddenFor.has("region"));
    this.layout();
  }

  /**
   * 页面列表变形之前拍下前台网页此刻的画面:渲染层铺回原处,再请这边把原生视图挪开(见 setForegroundHidden 的
   * "cover"),列表就能在那张画面上展开、收起。`bounds` 是网页在窗口里**该在**的位置 —— 已经挪开了也一样。
   * 没有前台网页 / 拍不到时 null。
   */
  async snapshotForeground(): Promise<ForegroundSnapshot | null> {
    const view = this.visibleId ? this.views.get(this.visibleId) : null;
    if (!this.alive(view)) return null;
    const image = await view.webContents.capturePage();
    if (image.isEmpty()) return null;
    // JPEG:整窗大小的画面编 PNG 要上百毫秒,鼠标停上去等它就显得迟钝;只是临时铺一下的底图。
    return { frame: `data:image/jpeg;base64,${image.toJPEG(90).toString("base64")}`, bounds: this.foregroundBounds() };
  }

  /** 前台网页在窗口里该在的位置:顶栏下面,左边让出页面列表、右边让出侧栏。 */
  private foregroundBounds(): { x: number; y: number; width: number; height: number } {
    const [width, height] = this.window && !this.window.isDestroyed() ? this.window.getContentSize() : [0, 0];
    return {
      x: this.shellInsetLeft,
      y: EMBED_HEADER_HEIGHT,
      width: Math.max(0, width - this.shellInsetLeft - this.shellInsetRight),
      height: Math.max(0, height - EMBED_HEADER_HEIGHT),
    };
  }

  /** 换了前台视图 / 收起了:侧栏让出的宽度和暂时的隐藏都不该留给下一个视图。 */
  private resetShell(): void {
    this.shellInsetRight = 0;
    for (const reason of [...this.foregroundHiddenFor]) this.setForegroundHidden(reason, false);
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
    if (!this.alive(view)) {
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
    // 会话关掉(运行结束、取消、用户关窗)时,它开着的**每一页**都收回 —— 不只当前那一页。
    for (const page of this.tabs.get(accountId)?.list().map(({ item }) => item) ?? []) {
      page.driver.detach();
      if (!this.alive(page.view)) continue;
      try {
        page.view.webContents.close();
      } catch {
        // already gone
      }
    }
    // 关闭会触发 webContents 的 destroyed → forget;这里再走一次,是为了不依赖那个事件一定到达
    // (视图本来就已经没了的情况下它不会再来)。forget 幂等。
    this.forget(accountId);
  }

  /**
   * Wipe the account's persisted login state (cookies, localStorage, caches).
   *
   * 池档案的分区名来自数据库,本次运行没打开过的档案不在 partitions 里 —— 调用方把分区名一起
   * 给过来,否则会按发布账号的约定拼出一个根本不存在的分区,清了个寂寞。
   */
  async clearAccountData(accountId: string, partitionName?: string): Promise<void> {
    this.destroy(accountId);
    const partition = partitionName ?? this.partitionFor(accountId);
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
    this.hover.dispose();
    for (const accountId of [...this.views.keys()]) {
      this.destroy(accountId);
    }
  }

  private ensure(accountId: string): { view: WebContentsView; driver: PageDriver } {
    let view = this.views.get(accountId);
    // 尸体等于没有:留着它,下一次 show()/getDriver() 就会在 undefined 上取属性而炸。当前页没了就落到
    // 会话里的另一页;一页都不剩才算这个会话没了。
    if (view && !this.alive(view)) {
      this.dropTab(accountId, view);
      view = this.views.get(accountId);
      if (view && !this.alive(view)) {
        this.forget(accountId);
        view = undefined;
      }
    }
    if (!view) {
      const tab = this.createTab(accountId);
      const list = new PageList<PageTab>();
      list.add(tabId(tab), tab, { activate: true });
      this.tabs.set(accountId, list);
      this.views.set(accountId, tab.view);
      this.drivers.set(accountId, tab.driver);
      view = tab.view;
    }
    return { view, driver: this.drivers.get(accountId)! };
  }

  /**
   * 给会话建一个页面。`adopt`:window.open / target=_blank 开出来的那个 —— Chromium 已经为它建好了
   * WebContents(带着 opener 关系),这里把它收进一个视图,而不是另起一个。
   */
  private createTab(accountId: string, adopt?: Electron.BrowserWindowConstructorOptions): PageTab {
    const view = adopt
      ? // 第三方登录(TikTok 的「用 Google 继续」、各家的微信/QQ 授权)全靠 window.open:授权页办完事要
        // postMessage 回 `window.opener`,再自己 window.close()。收进来的正是 Chromium 为这个 window.open
        // 建的那个页面,opener 关系还在,授权照常回调;它 close() 掉的也只是这一页(见 dropTab),不是整个会话。
        new WebContentsView(adopt as unknown as Electron.WebContentsViewConstructorOptions)
      : new WebContentsView({
          webPreferences: {
            partition: this.partitionFor(accountId),
            backgroundThrottling: false,
            // 注入「返回」悬浮按钮(点击永远发生在聚焦的账号视图内,不会被 macOS 焦点切换吞掉)。
            preload: ACCOUNT_VIEW_PRELOAD,
            contextIsolation: true,
          },
        });
    const tab: PageTab = { view, driver: new PageDriver(view.webContents), favicon: "" };
    view.webContents.on("focus", () => {
      this.lastFocused = view.webContents;
    });
    const isCurrent = () => this.views.get(accountId) === view;
    // 授权页、新开的页面同样会读 UA 做风控:一律抹掉 Electron 字样(收进来的页面还没开始加载,来得及)。
    view.webContents.setUserAgent(platformUserAgent(view.webContents.getUserAgent()));
    // 新页面默认静音:它此刻不在前台。show() / switchPage 会按 syncAudio 的唯一判据放开。
    view.webContents.setAudioMuted(true);
    // 单页应用可能在用户解除面板静音后才创建播放器，或切集时替换 video 元素。
    // 每次媒体真正起播都重申网页侧状态，避免 Electron 已放行但页面仍 muted/volume=0。
    view.webContents.on("media-started-playing", () => {
      if (isCurrent() && this.isAudible(accountId)) this.syncPageMedia(accountId, true);
    });
    view.webContents.setWindowOpenHandler((details) => this.openWindow(accountId, view, details));
    // 下载不弹系统保存框:分区会话上接管(同一个会话只接一次,会话里的每一页都走它)。
    this.downloads.watch(view.webContents.session);
    // 页面在我们之外没掉(渲染进程崩溃 / 页面自己 window.close())时,账本要跟着清 —— 否则当前页指着
    // 一具尸体,顶部工具条收不回去,复用它的每一处都在 undefined 上取属性。
    const contentsId = view.webContents.id;
    view.webContents.on("destroyed", () => {
      this.media.forget(contentsId);
      this.dropTab(accountId, view);
    });
    // 换了一页:上一页看见过的视频不属于这一页。页内跳转(单页应用)不算。
    view.webContents.on("did-navigate", () => this.media.forget(contentsId));
    view.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedURL) => {
      console.warn("[mosael:view] load failed", {
        accountId,
        errorCode,
        errorDescription,
        url: validatedURL,
      });
    });
    // 从内嵌视图内可靠返回:顶栏「返回」是主窗口 HTML,内嵌视图抢焦点后首次点击常被 macOS
    // 吃掉(时灵时不灵)。键盘直接在视图 webContents 上收——无论焦点在谁那儿都稳。
    //
    // 但**单击 Esc 不能用**:Esc 在网页里是「关掉当前这层」的通用键 —— 弹窗、下拉、验证浮层
    // 全靠它。我们不 preventDefault,于是一次 Esc 同时被页面和这里收走:用户想关掉 Google 登录
    // 的验证浮层,结果整个内嵌浏览器缩回了 app,登录被打断。实测就是这么发生的。
    //
    // 改成**连按两次**(700ms 内):第一次纯粹留给页面,第二次才是「我要退出这个内嵌浏览器」。
    // 网页几乎不会把连按 Esc 定义成别的操作,而用户想退出时连按两下是自然动作。
    //
    // **正在网页里打字时两次都留给网页**:编辑器、搜索框、表单里连按 Esc(收起补全、退出编辑)再常见不过,
    // 这时把人拽回 Mosael 就是截走了网页的键。问一下网页焦点在不在可编辑元素上,在就不退。
    let lastEscapeAt = 0;
    view.webContents.on("before-input-event", (_event, input) => {
      if (input.type !== "keyDown" || input.key !== "Escape") return;
      const now = Date.now();
      if (now - lastEscapeAt <= DOUBLE_ESCAPE_MS) {
        lastEscapeAt = 0;
        void typingIn(view.webContents).then((typing) => {
          if (!typing && this.visibleId === accountId) this.hide();
        });
        return;
      }
      lastEscapeAt = now;
    });
    // 指针在不在这块面板的网页上 —— 渲染层看不见原生视图上的鼠标,缩放手柄要靠这个才能在
    // 悬停网页时亮出来。只看不拦(从不 preventDefault),页面照常收到每一个事件。见 PanelHover。
    view.webContents.on("before-mouse-event", (_event, mouse) => {
      if (!isCurrent() || this.visibleId === accountId || !this.panels.includes(accountId)) return;
      this.hover.observe(accountId, mouse.type);
    });
    // 地址/标题/加载态变化 → 刷新工具栏和页面列表(仅当前可见的会话才广播;列表里别的页面改了标题也要刷)。
    const sync = () => {
      if (this.visibleId === accountId) this.emit();
      // 导航后必须**重新**设一次面板缩放。Chromium 的缩放策略是 same-origin(Electron 文档原话:
      // "The zoom policy at the Chromium level is same-origin"),所以挂面板时设的 0.3 只对当时那个
      // 域名有效 —— 一 goto 到新域名就回到 1,页面按 1:1 渲染再被 384×240 裁掉,只能看见左上角一块。
      // 线上就是这么表现的(百度导航栏字号正常、内容被切)。
      if (isCurrent()) this.applyPanelZoom(accountId);
    };
    view.webContents.on("did-navigate", sync);
    view.webContents.on("did-navigate-in-page", sync);
    view.webContents.on("did-start-loading", sync);
    view.webContents.on("did-stop-loading", sync);
    view.webContents.on("did-finish-load", sync);
    view.webContents.on("page-title-updated", sync);
    view.webContents.on("page-favicon-updated", (_event, favicons) => {
      tab.favicon = favicons.find((one) => /^https?:\/\//i.test(one)) ?? "";
      if (this.visibleId === accountId) this.emit();
    });
    view.setBackgroundColor("#ffffff");
    return tab;
  }

  /**
   * 页面要开新窗口(window.open、target=_blank):**收进这个会话的页面列表并切过去**,不再弹一个
   * 520×700 的独立小窗 —— 那个小窗盖在应用上、关掉主窗口它还在,自动化也够不着它(驱动只盯着原页面)。
   *
   * 危险 scheme(javascript:/file:/data: …)照旧一律不开;开满了(MAX_PAGES)也不开,并记下时刻,
   * 前台的话由页面列表提示一句。后台打开(中键 / ⌘ 点击)的只加进列表,不切过去。
   */
  private openWindow(
    accountId: string,
    opener: WebContentsView,
    details: Electron.HandlerDetails,
  ): Electron.WindowOpenHandlerResponse {
    let protocol = "";
    try {
      protocol = new URL(details.url).protocol;
    } catch {
      /* 非法 URL */
    }
    if (protocol !== "http:" && protocol !== "https:") return { action: "deny" };
    const list = this.tabs.get(accountId);
    if (!list || list.full) {
      this.pageLimitHitAt = Date.now();
      console.warn("[mosael:view] page limit reached, new window refused", { accountId, limit: MAX_PAGES });
      if (this.visibleId === accountId) this.emit();
      return { action: "deny" };
    }
    return {
      action: "allow",
      // 关掉开它的那一页时,它开出来的页面照样留着:在列表里它们是平级的页面,不是附属的弹窗
      // (Electron 默认会把子窗口跟着 opener 一起关掉 —— 实跑里关掉一页,它开过的两页一起没了)。
      outlivesOpener: true,
      createWindow: (options) =>
        this.addTab(accountId, options, {
          activate: details.disposition !== "background-tab",
          after: String(opener.webContents.id),
        }).view.webContents,
    };
  }

  /** 往会话里加一页(新窗口收进来的、用户新建的),放在 `after` 那一页后面。 */
  private addTab(
    accountId: string,
    adopt: Electron.BrowserWindowConstructorOptions | undefined,
    opts: { activate: boolean; after?: string | null },
  ): PageTab {
    const list = this.tabs.get(accountId)!;
    const tab = this.createTab(accountId, adopt);
    list.add(tabId(tab), tab, { activate: false, after: opts.after });
    if (opts.activate) this.switchPage(accountId, tabId(tab));
    else {
      if (this.visibleId === accountId) this.emit();
      this.layout(); // 面板卡片上的页数
    }
    return tab;
  }

  /**
   * 切到会话里的某一页:它挂到窗口上原来那一页的位置(前台全屏或面板,缩放跟着),原来那一页摘下来
   * 留在后台活着、静音。返回切成没有。
   */
  switchPage(accountId: string, pageId: string): boolean {
    const list = this.tabs.get(accountId);
    const tab = list?.get(pageId);
    if (!list || !tab || !this.alive(tab.view)) return false;
    const previous = this.views.get(accountId);
    list.setCurrent(pageId);
    if (previous === tab.view) return true;
    this.views.set(accountId, tab.view);
    this.drivers.set(accountId, tab.driver);
    const shown = this.visibleId === accountId;
    const panelled = !shown && this.panels.includes(accountId);
    if (this.window && !this.window.isDestroyed() && (shown || panelled)) {
      if (previous) {
        try {
          this.window.contentView.removeChildView(previous);
        } catch {
          // 原来那一页已经没了(关掉的正是它)
        }
      }
      this.window.contentView.addChildView(tab.view);
      if (shown) {
        tab.view.webContents.setZoomFactor(1);
        void tab.driver.clearMetricsOverride();
        tab.view.setVisible(!this.foregroundHiddenFor.has("region"));
        // 切到这一页了,键盘跟着到这一页。
        tab.view.webContents.focus();
      } else {
        this.applyPanelZoom(accountId);
        // addChildView 把它放到了最上面;卡片堆里排在它上面的那几张(和前台视图)要回到它上面去。
        for (const id of this.panels.slice(this.panels.indexOf(accountId) + 1)) {
          const above = this.views.get(id);
          if (id !== this.visibleId && this.alive(above)) this.window.contentView.addChildView(above);
        }
        const front = this.visibleId ? this.views.get(this.visibleId) : null;
        if (this.alive(front)) this.window.contentView.addChildView(front);
      }
    }
    if (previous && this.alive(previous)) previous.webContents.setAudioMuted(true);
    this.syncAudio();
    this.layout();
    if (shown) this.emit();
    return true;
  }

  /**
   * 一页没了(关掉了 / 页面自己 window.close() / 崩了):从列表里拿掉;是当前页就落到它上面那一页
   * (关掉弹出来的授权页,回到开它的那一页);一页都不剩,这个会话就没了。
   */
  private dropTab(accountId: string, view: WebContentsView): void {
    const list = this.tabs.get(accountId);
    const entry = list?.list().find(({ item }) => item.view === view);
    if (!list || !entry) {
      // 不在任何列表里(还没登记就没了):老办法,整个会话当没了。
      if (this.views.get(accountId) === view) this.forget(accountId);
      return;
    }
    const wasCurrent = this.views.get(accountId) === view;
    entry.item.driver.detach();
    if (this.window && !this.window.isDestroyed()) {
      try {
        this.window.contentView.removeChildView(view);
      } catch {
        // 已经摘掉了
      }
    }
    const next = list.remove(entry.id);
    if (next === null || list.size === 0) {
      this.forget(accountId);
      return;
    }
    if (wasCurrent) this.switchPage(accountId, next);
    else {
      if (this.visibleId === accountId) this.emit();
      this.layout();
    }
  }

  /** 关掉会话里的一页。最后一页不关(那是关掉整个浏览器,走「返回」/「关闭浏览器」),返回关成没有。 */
  closePage(accountId: string, pageId: string): boolean {
    const list = this.tabs.get(accountId);
    const tab = list?.get(pageId);
    if (!list || !tab || list.size <= 1) return false;
    try {
      tab.view.webContents.close();
    } catch {
      // 已经没了
    }
    this.dropTab(accountId, tab.view); // close 会触发 destroyed → dropTab;不依赖它一定到达(幂等)
    return true;
  }

  /** 会话里的页面,按列表次序。 */
  pagesOf(accountId: string): PageSummary[] {
    const list = this.tabs.get(accountId);
    const current = this.views.get(accountId);
    return (list?.list() ?? [])
      .filter(({ item }) => this.alive(item.view))
      .map(({ id, item }) => ({
        id,
        title: item.view.webContents.getTitle(),
        url: item.view.webContents.getURL(),
        favicon: item.favicon,
        current: item.view === current,
      }));
  }

  /** 按第几个 / 标题 / 网址找会话里的一页(自动化的「切换页面」用);找不到是 null。 */
  findPage(accountId: string, match: PageMatch): string | null {
    const list = this.tabs.get(accountId);
    if (!list) return null;
    return list.find(match, (tab) =>
      this.alive(tab.view)
        ? { title: tab.view.webContents.getTitle(), url: tab.view.webContents.getURL() }
        : { title: "", url: "" },
    );
  }

  /** 当前页的 id(自动化「关闭当前页」用)。 */
  currentPageId(accountId: string): string | null {
    return this.tabs.get(accountId)?.current()?.id ?? null;
  }

  // ---- 页面列表(渲染层左侧那一列):都作用在前台那个会话上,渲染层不点名要哪个会话 ----

  /** 前台会话新建一页并打开地址(地址栏同一套归一:补协议、不像网址就去搜)。开满了返回 false。 */
  newPage(rawUrl: string): boolean {
    const id = this.visibleId;
    const list = id ? this.tabs.get(id) : null;
    if (!id || !list) return false;
    if (list.full) {
      this.pageLimitHitAt = Date.now();
      this.emit();
      return false;
    }
    const tab = this.addTab(id, undefined, { activate: true, after: list.current()?.id ?? null });
    const url = normalizeAddress(rawUrl);
    if (url) void tab.view.webContents.loadURL(url);
    return true;
  }

  switchVisiblePage(pageId: string): boolean {
    return this.visibleId ? this.switchPage(this.visibleId, pageId) : false;
  }

  closeVisiblePage(pageId: string): boolean {
    return this.visibleId ? this.closePage(this.visibleId, pageId) : false;
  }

  /** 拖动重排前台会话的页面。给的次序要和现有的一一对上(见 PageList.reorder)。 */
  reorderVisiblePages(ids: string[]): boolean {
    const list = this.visibleId ? this.tabs.get(this.visibleId) : null;
    if (!list?.reorder(ids)) return false;
    this.emit();
    return true;
  }

  /** 页面列表开合:前台视图左侧让出这么宽(收起成图标条时窄,展开时宽,不挂列表时是 0)。 */
  setPagesInset(left: number): void {
    const width = this.window && !this.window.isDestroyed() ? this.window.getContentSize()[0] : 0;
    // 至多三分之一:列表再宽也不能把网页挤没了。
    const next = Math.max(0, Math.min(Math.round(left), Math.floor(width / 3)));
    if (next === this.shellInsetLeft) return;
    this.shellInsetLeft = next;
    this.layout();
  }

  private partitionFor(id: string): string {
    // 登记过的(池档案)用其显式分区;未登记的(发布账号)按约定 persist:<prefix>-<id>。
    const partition = this.partitions.get(id) ?? `persist:${PARTITION_PREFIX}-${id}`;
    // 拿分区名的每条路径最终都会落到这里,所以遗留目录的惰性改名挂在这一处即可(幂等)。
    return partition;
  }

  private detachView(accountId: string): void {
    const view = this.views.get(accountId);
    if (!view || !this.window || this.window.isDestroyed()) return;
    try {
      this.window.contentView.removeChildView(view);
    } catch {
      // 视图已经没了 —— 摘不掉也无所谓,forget 接着往下清账本。
    }
  }

  private layout(): void {
    if (!this.window || this.window.isDestroyed()) {
      return;
    }
    const [width, height] = this.window.getContentSize();

    // 前台全屏视图:铺满内容区(顶部留出渲染层自己画的工具条)。页面列表盖着它变形时整块挪到窗口外,大小照旧。
    const visible = this.visibleId ? this.views.get(this.visibleId) : null;
    if (this.alive(visible)) {
      const bounds = this.foregroundBounds();
      visible.setBounds(this.foregroundHiddenFor.has("cover") ? { ...bounds, x: -(bounds.width + OFF_WINDOW_GAP) } : bounds);
    }

    // 悬浮面板:右下角卡片堆,后挂的在上,下层的卡片往上错开、露出标题条;网页全部叠在最上面那张
    // 的网页区域里(为什么见 panelStack)。面板必须**整块落在可视区内** —— 实测挂进窗口但 bounds
    // 移出屏幕的视图视口是 0×0,布局与命中测试双双失效,可信输入就白费了。
    // 已在前台全屏的那块不再按面板摆。
    const mounted = this.panels.filter(
      (accountId) => accountId !== this.visibleId && this.alive(this.views.get(accountId)),
    );
    const stack = panelStack(this.panelLayout, { width, height }, mounted.length);
    const cards: PanelCard[] = mounted.map((accountId, index) => {
      const view = this.views.get(accountId)!;
      view.setBounds(stack.page);
      // 卡片外廓:渲染层照这个矩形画圆角、边框、阴影和标题条。
      return {
        id: accountId,
        ...stack.cards[index],
        header: PANEL.header,
        radius: PANEL.radius,
        muted: view.webContents.isAudioMuted(),
        hovered: this.hover.has(accountId),
        pages: this.tabs.get(accountId)?.size ?? 1,
        page: this.tabs.get(accountId)?.currentIndex() || 1,
      };
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
      title: wc ? wc.getTitle() : "",
      partition: this.visibleId ? this.partitionFor(this.visibleId) : null,
      pages: this.visibleId ? this.pagesOf(this.visibleId) : [],
      pageLimit: MAX_PAGES,
      pageLimitHitAt: this.pageLimitHitAt,
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
  onDownload?: (notice: DownloadNotice) => void,
): AccountViewManager {
  shared = new AccountViewManager(onViewChanged, onPanelsChanged, onDownload);
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
