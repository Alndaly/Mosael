import { app, screen, session, WebContentsView, type BaseWindow } from "electron";
import fs from "node:fs";
import path from "node:path";
import { EMBED_HEADER_HEIGHT, type ViewState } from "./types";
import { MediaRecorder } from "./mediaRecorder";
import { PageDriver } from "./pageDriver";
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

/** 连按两次 Esc 判定为「退出内嵌浏览器」的时间窗(见 ensure() 里的 before-input-event)。 */
const DOUBLE_ESCAPE_MS = 700;

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
}

/**
 * 渲染层对面板几何的一次改动:要么拖标题条挪位置,要么拖某个手柄缩放。缩放给的是指针要的矩形
 * (不带约束),比例、上下限与窗口边界由 panelGeometry 定。
 */
export type PanelLayoutChange = { x: number; y: number } | ({ handle: PanelHandle } & PanelRect);

/**
 * Owns one embedded WebContentsView per account. Each view uses a persistent
 * session partition (`persist:mosael-<id>`) so cookies / localStorage are isolated
 * and survive restarts — this replaces the old Playwright per-account profile
 * directory. The view is laid into the host BaseWindow below a fixed header
 * strip that the renderer keeps clear for its own controls.
 */
export class AccountViewManager {
  private views = new Map<string, WebContentsView>();
  private drivers = new Map<string, PageDriver>();
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
   * 框选截图时前台视图暂时藏起来:渲染层在原处铺一张冻结的画面让人拖框(原生视图上画不了框)。
   * 只藏不摘 —— 页面不重排、不暂停,框完原样亮回来。
   */
  private foregroundHidden = false;
  /** 前台视图收到过的媒体响应(「下载页面里的视频」要用,见 mediaRecorder)。 */
  readonly media = new MediaRecorder();

  constructor(
    private readonly onViewChanged: (state: ViewState) => void = noop,
    private readonly onPanelsChanged: (cards: PanelCard[]) => void = () => undefined,
  ) {}

  attachWindow(window: BaseWindow, nameResolver: (accountId: string) => string | null): void {
    this.window = window;
    this.nameOf = nameResolver;
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

  /** 已建好的驱动(不新建)。 */
  existingDriver(viewId: string): PageDriver | null {
    return this.drivers.get(viewId) ?? null;
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
    for (const [id, view] of this.views) {
      if (!this.alive(view)) continue;
      view.webContents.setAudioMuted(!this.isAudible(id));
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

  /** 侧栏开合:前台视图右侧让出这么宽(见 shellInsetRight)。 */
  setShellInset(right: number): void {
    const width = this.window && !this.window.isDestroyed() ? this.window.getContentSize()[0] : 0;
    // 至少给网页留一半:侧栏再宽也不能把页面挤没了。
    const next = Math.max(0, Math.min(Math.round(right), Math.floor(width / 2)));
    if (next === this.shellInsetRight) return;
    this.shellInsetRight = next;
    this.layout();
  }

  /** 框选截图期间藏起 / 亮回前台视图(见 foregroundHidden)。 */
  setForegroundHidden(hidden: boolean): void {
    this.foregroundHidden = hidden;
    const view = this.visibleId ? this.views.get(this.visibleId) : null;
    if (this.alive(view)) view.setVisible(!hidden);
  }

  /** 换了前台视图 / 收起了:侧栏让出的宽度和框选的隐藏都不该留给下一个视图。 */
  private resetShell(): void {
    this.shellInsetRight = 0;
    if (this.foregroundHidden) this.setForegroundHidden(false);
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
    this.drivers.get(accountId)?.detach();
    const view = this.views.get(accountId);
    if (this.alive(view)) {
      try {
        view.webContents.close();
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
    // 尸体等于没有:留着它,下一次 show()/getDriver() 就会在 undefined 上取属性而炸。
    if (view && !this.alive(view)) {
      this.forget(accountId);
      view = undefined;
    }
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
      // 新视图默认静音:它此刻不在前台。show() 会按 syncAudio 的唯一判据放开。
      view.webContents.setAudioMuted(true);
      // 单页应用可能在用户解除面板静音后才创建播放器，或切集时替换 video 元素。
      // 每次媒体真正起播都重申网页侧状态，避免 Electron 已放行但页面仍 muted/volume=0。
      view.webContents.on("media-started-playing", () => {
        if (this.isAudible(accountId)) this.syncPageMedia(accountId, true);
      });
      view.webContents.setWindowOpenHandler(({ url }) => {
        // **弹窗要真的开成弹窗**,不能塞进本视图导航。
        //
        // 第三方登录(TikTok 的「用 Google 继续」、各家的微信/QQ 授权)全靠 window.open:授权页
        // 办完事要 postMessage 回 `window.opener`,然后自己 window.close()。把它改成在本视图里
        // 导航,这两件事同时坏掉 —— opener 被顶掉了,回调没人接;而那句 window.close() 关掉的是
        // 整个账号视图,用户看到的就是"转了一会儿,内嵌浏览器自己退出了"。实测 TikTok 的 Google
        // 登录正是这样。
        //
        // 安全那一半保持不变:危险 scheme(javascript:/file:/data: …)一律不开 —— 当初拦的是
        // scheme,不是"弹窗"这件事本身。
        //
        // 代价:平台若用新窗口打开某个页面,驱动仍然只盯着原视图。目前各适配器都是自己 goto 到
        // 明确 URL、不依赖"页面替我导航",所以不受影响。
        try {
          const proto = new URL(url).protocol;
          if (proto === "http:" || proto === "https:") {
            return {
              action: "allow",
              overrideBrowserWindowOptions: {
                width: 520,
                height: 700,
                autoHideMenuBar: true,
                // 分区必须显式写死:授权拿到的 cookie 要落在**这个账号**的分区里,而不是默认会话。
                webPreferences: {
                  partition: this.partitionFor(accountId),
                  preload: ACCOUNT_VIEW_PRELOAD,
                  contextIsolation: true,
                },
              },
            };
          }
        } catch {
          /* 非法 URL,忽略 */
        }
        return { action: "deny" };
      });
      // 弹窗也要抹掉 UA 里的 Electron 字样 —— 授权页同样会读 UA 做风控。
      view.webContents.on("did-create-window", (child) => {
        child.webContents.setUserAgent(platformUserAgent(child.webContents.getUserAgent()));
      });
      // 视图在我们之外没掉(渲染进程崩溃 / 页面自己 window.close())时,账本要跟着清 ——
      // 否则 visibleId 会一直指着它,顶部工具条永远收不回去,而复用它的每一处都在 undefined 上取属性。
      const contentsId = view.webContents.id;
      view.webContents.on("destroyed", () => {
        this.media.forget(contentsId);
        this.forget(accountId);
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
      let lastEscapeAt = 0;
      view.webContents.on("before-input-event", (_event, input) => {
        if (input.type !== "keyDown" || input.key !== "Escape") return;
        const now = Date.now();
        if (now - lastEscapeAt <= DOUBLE_ESCAPE_MS) {
          lastEscapeAt = 0;
          this.hide();
          return;
        }
        lastEscapeAt = now;
      });
      // 指针在不在这块面板的网页上 —— 渲染层看不见原生视图上的鼠标,缩放手柄要靠这个才能在
      // 悬停网页时亮出来。只看不拦(从不 preventDefault),页面照常收到每一个事件。见 PanelHover。
      view.webContents.on("before-mouse-event", (_event, mouse) => {
        if (this.visibleId === accountId || !this.panels.includes(accountId)) return;
        this.hover.observe(accountId, mouse.type);
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
      view.webContents.on("page-title-updated", sync);
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

    // 前台全屏视图:铺满内容区(顶部留出渲染层自己画的工具条)。
    const visible = this.visibleId ? this.views.get(this.visibleId) : null;
    if (this.alive(visible)) {
      visible.setBounds({
        x: 0,
        y: EMBED_HEADER_HEIGHT,
        width: Math.max(0, width - this.shellInsetRight),
        height: Math.max(0, height - EMBED_HEADER_HEIGHT),
      });
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
