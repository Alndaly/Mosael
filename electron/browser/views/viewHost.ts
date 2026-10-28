// 内嵌浏览器的**视图宿主**:在主窗口里建好、销毁那一套共享的内嵌视图(AccountViewManager),以及画在网页上面的
// 浮层(悬停说明、提示条)和浮层让位;再把顶栏工具条、页面列表、悬浮面板这些「对前台视图的操作」交给主进程。
//
// **它不认识发布、ComfyUI、RPA。** 那三件事都要用同一套视图,于是视图归这里,它们从 `hostedViews()` 取:
// 此前这一切都写在 publish/publishWorker 里,RPA 为了调一次 ComfyUI 工作台得 import 发布执行器,
// 而 ComfyUI 工作台和池档案登录都只是借发布的视图在跑(见 browser/layering.test.ts)。
import type { BaseWindow } from "electron";

import { t as tr } from "../../i18n.cjs";
import { plog } from "../log";
import type { ViewState } from "../types";
import {
  createSharedViews,
  destroySharedViews,
  type AccountViewManager,
  type ForegroundSnapshot,
  type PanelCard,
  type PanelLayoutChange,
} from "./accountViews";
import type { DownloadNotice } from "./downloads";
import { FloatLayer, type FloatHint, type FloatPointer } from "./floatLayer";
//: 声明式让位(P2):浮层只说「要哪种让法」,折算成对原生视图的指令在这里做一次。
import { createHostLayers } from "./hostLayers.cjs";

let views: AccountViewManager | null = null;
let floatLayer: FloatLayer | null = null;
/** 原生视图在前台时右下角的提示条画在这一块上(ADR 0051);提示条上的按钮靠它把指针交回渲染层。 */
let toastLayer: FloatLayer | null = null;

export interface ViewHostOptions {
  window: BaseWindow;
  onViewChanged?: (state: ViewState) => void;
  getAccountName?: (accountId: string) => string | null;
  /** 悬浮卡片几何变化 —— 渲染层照它画圆角/阴影/标题条(原生 View 画不了)。 */
  onPanels?: (cards: PanelCard[]) => void;
  /** 用户在内嵌浏览器里点的下载:进度、下好了、没下成(渲染层据此存进素材库并在顶栏说一句)。 */
  onDownload?: (notice: DownloadNotice) => void;
  /** 提示条那一块浮层视图上的指针(主窗口的 CSS 坐标):渲染层据此点真的那条提示(ADR 0051)。 */
  onToastsPointer?: (pointer: FloatPointer) => void;
  /** 内嵌网页、工作台画布里按了 ⌘K:交给渲染层开命令面板(ADR 0051)。 */
  onCommandPalette?: () => void;
}

/** 在主窗口里建好视图宿主。已经建过就什么都不做(mac 关窗→重新激活:主进程先 stop 再 start)。 */
export function startViewHost(opts: ViewHostOptions): void {
  if (views) return;
  // 浮层视图(外壳里的悬停说明画在网页上面):内嵌浏览器一亮出来就先建好,收回去时收起说明。
  floatLayer = new FloatLayer(opts.window, () => views?.focusTarget() ?? null);
  toastLayer = new FloatLayer(opts.window, () => views?.focusTarget() ?? null, {
    kind: "toasts",
    onPointer: (pointer) => opts.onToastsPointer?.(pointer),
  });
  const onViewChanged = (state: ViewState) => {
    if (state.visible) floatLayer?.warm();
    else {
      floatLayer?.hide();
      toastLayer?.hide();
    }
    opts.onViewChanged?.(state);
  };
  // 共享实例:发布、ComfyUI 工作台、浏览器(RPA/智能体)执行器用的是同一个管理器(见 accountViews.createSharedViews)。
  views = createSharedViews(onViewChanged, opts.onPanels, opts.onDownload, () => opts.onCommandPalette?.());
  views.attachWindow(opts.window, opts.getAccountName ?? (() => null));
}

/** 销毁视图宿主,让下次 startViewHost 能绑定新窗口。持久化会话在磁盘分区里(persist:mosael-<id>),销毁视图不丢登录态。 */
export function stopViewHost(): void {
  destroySharedViews();
  views = null;
  floatLayer?.destroy();
  floatLayer = null;
  toastLayer?.destroy();
  toastLayer = null;
}

/** 宿主建好的那套视图;没建(或已销毁)是 null。发布、ComfyUI 工作台每次用都来这里取,不各自攥一份旧的。 */
export function hostedViews(): AccountViewManager | null {
  return views;
}

/** 浏览器池通用档案登录:复用发布账号那套**内嵌视图**(AccountViewManager.openView),在该档案分区
 *  亮出登录页,不弹外部系统窗。与 openLogin 一样占前台单槽——已有视图在前台则拒绝。viewId = 分区名。
 *  通用档案没有平台适配器/登录态轮询,登不登成由用户自己判断(cookie 落分区即可)。 */
export async function openPoolLogin(opts: {
  partition: string;
  url: string;
  name?: string;
  proxy?: string | null;
  resume?: boolean;
  /** 档案钉的浏览器身份(见 BrowserProfile.identity);不传就按平台规矩。 */
  identity?: string | null;
}): Promise<void> {
  if (!views) throw new Error(tr("publishErr_notReady"));
  if (views.visibleAccountId && views.visibleAccountId !== opts.partition)
    throw new Error(tr("publishErr_foregroundBusy"));
  //: **建视图之前**定身份(UA 随第一次请求发出去),见 accountViews.applyIdentity。
  if (opts.identity) views.setAccountIdentity(opts.partition, opts.identity);
  await views.openView({
    viewId: opts.partition,
    partition: opts.partition,
    name: opts.name,
    url: opts.url,
    proxy: opts.proxy ?? null,
    resume: opts.resume === true,
  });
}

/** 通用档案「清除登录数据」:和退出登录同一件事,只是这里没有平台、也没有登录态要回写。 */
export async function clearPoolProfile(partition: string): Promise<void> {
  if (!views) throw new Error(tr("publishErr_notReady"));
  // 池档案的视图 id 就是分区名(见 openPoolLogin)。
  await views.clearAccountData(partition, partition);
  plog("pool profile cleared:", partition);
}

/** 渲染层重新加载之后,把当前内嵌视图状态补播一次(见 AccountViewManager.republish)。 */
export function republishViewState(): void {
  views?.republish();
}

/** 主窗口的页面缩放变了(「视图 → 放大 / 缩小」):视图按新的缩放重新摆(见 AccountViewManager.hostZoom)。 */
export function hostZoomChanged(): void {
  views?.hostZoomChanged();
}

/** 内嵌视图此刻是否占着前台 —— 主进程据此决定 ⌘R 刷的是内嵌页面还是应用本身。 */
export function embeddedViewVisible(): boolean {
  return Boolean(views?.visibleAccountId);
}

/** 内嵌浏览器工具栏:导航当前可见视图。 */
export function navigateView(url: string): void {
  views?.navigate(url);
}
export function viewBack(): void {
  views?.back();
}
export function viewForward(): void {
  views?.forward();
}
export function viewReload(): void {
  views?.reload();
}

/** 前台会话的页面列表(渲染层左侧那一列):切换、关闭、重排、新建、让出左侧。 */
export function switchViewPage(id: string): boolean {
  return views?.switchVisiblePage(id) ?? false;
}
export function closeViewPage(id: string): boolean {
  return views?.closeVisiblePage(id) ?? false;
}
export function reorderViewPages(ids: string[]): boolean {
  return views?.reorderVisiblePages(ids) ?? false;
}
export function newViewPage(url: string): boolean {
  return views?.newPage(url) ?? false;
}
/** 页面列表展开、收起、临时展开:先拍下前台网页的画面(渲染层铺回原处),再把原生视图挪开 / 放回原处。 */
export function snapshotViewPage(): Promise<ForegroundSnapshot | null> {
  return views?.snapshotForeground() ?? Promise.resolve(null);
}
/** 键盘交给前台网页(顶栏、页面列表里点完之后)。 */
export function focusViewPage(): void {
  views?.focusForeground();
}

/** 原生网页占着前台时,菜单的 ⌘C 先问 Mosael 自己的选中文字;没有才落回网页。 */
export function copyHostSelectionIfAny(): Promise<boolean> {
  if (!views?.visibleAccountId) return Promise.resolve(false);
  return views.copyHostSelectionIfAny();
}

/** 键盘交回 Mosael 的渲染层(点在工作台那一列、发布顶栏等壳里之后)。 */
export function focusHostWindow(): void {
  views?.focusHost();
}
/** 外壳里的悬停说明画到网页上面 / 收起(见 floatLayer)。 */
export function showFloat(hint: FloatHint): Promise<void> {
  return floatLayer?.show(hint) ?? Promise.resolve();
}
export function hideFloat(id?: string): void {
  floatLayer?.hide(id);
}
/** 原生视图在前台时,右下角的提示条画到网页上面 / 收起(ADR 0051)。 */
export function showToasts(toasts: Omit<FloatHint, "id">): Promise<void> {
  return toastLayer?.show({ id: "toasts", ...toasts }) ?? Promise.resolve();
}
export function hideToasts(): void {
  toastLayer?.hide();
}

/** 渲染层拖动/缩放悬浮面板后落到这里(几何由主进程持有:layout() 要用,还要落盘)。 */
export function setPanelLayout(change: PanelLayoutChange): void {
  views?.setPanelLayout(change);
}

/** 手动关闭某块悬浮面板:只撤面板,任务/会话照常继续跑(它不依赖面板)。 */
export function closePanel(id: string): void {
  views?.panelDetach(id);
}

/**
 * 渲染层的弹窗开着时把悬浮面板收起来(原生视图永远压在渲染层之上,见 AccountViewManager.setPanelsHidden)。
 * 与 closePanel 不同:只藏,任务照常继续,关掉弹窗再放回来。
 */
export function setPanelsHidden(hidden: boolean): void {
  views?.setPanelsHidden(hidden);
}

/**
 * 声明式让位(P2):浮层发一条声明,这里把**所有**在生效的声明折算成指令。
 *
 * 为什么不再让每个浮层各调一条通道:每加一个浮层就要记得接一次,漏接的表现是「被网页盖住、点不到」,
 * 而且不报错。现在只有这一处懂「几条声明怎么合成」,新浮层只要说清楚自己要哪种让法。
 */
const hostLayers = createHostLayers();

export function setHostLayer(claim: { id: string; kind: string; active: boolean; width?: number }): void {
  const directives = hostLayers.set(claim.id, claim);
  applyHostLayers(directives);
}

/** 浮层卸载:撤掉它那条声明(否则它会一直占着让位,网页永远缩着)。 */
export function clearHostLayer(id: string): void {
  applyHostLayers(hostLayers.clear(id));
}

function applyHostLayers(directives: {
  reasons: string[];
  panelsHidden: boolean;
  insetRight: number;
  insetLeft: number;
}): void {
  if (!views) return;
  for (const reason of ["region", "cover", "overlay"] as const) {
    views.setForegroundHidden(reason, directives.reasons.includes(reason));
  }
  views.setPanelsHidden(directives.panelsHidden);
  views.setShellInset(directives.insetRight);
  views.setPagesInset(directives.insetLeft);
}

/** 悬浮浏览器声音由 Electron 层控制,页面脚本无法绕过也不会因 SPA 导航失效。 */
export function setPanelMuted(id: string, muted: boolean): void {
  views?.setPanelMuted(id, muted);
}

/** 收起内嵌视图,把窗口还给 React UI。 */
export function hideEmbeddedView(): void {
  views?.hide();
}
