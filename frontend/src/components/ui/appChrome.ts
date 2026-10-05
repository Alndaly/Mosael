/**
 * **窗口外壳**:内嵌网页视图亮着时盖在应用最上层的浏览器顶栏、页面列表、侧栏、框选浮层(App 的 PublishViewBar、
 * BrowserPageList、ToolDrawer、RegionOverlay)。
 *
 * 它们和底下开着的弹窗没有关系,却在弹窗外面。模态弹窗(Radix 的 Dialog / Sheet)会:
 * - 把点在外面的那一下当成「点了弹窗外面」,把弹窗关掉 —— 真机上就是这样:工作流库「在编辑器里打开」之后点
 *   「返回 Mosael」,回来工作流库没了,得重新打开、重新找到那一张;
 * - 把 body 设成 `pointer-events: none`,外壳跟着点不动(styles.css 给外壳放开);
 * - 把焦点圈在自己里面:点地址栏,焦点马上被拽回弹窗,一个字也打不进去;
 * - 按 Esc 就关:在地址栏按 Esc 想撤销输入,底下的弹窗关了。
 * - 锁住滚动:遮罩(Radix 的 Overlay 里那层 react-remove-scroll)在 document 上听 wheel / touchmove,落在弹窗外面的
 *   一律 preventDefault —— 外壳里能点、能悬停,滚轮却滚不动(工作台右边那一列:「应用」面板超出一屏,滚不下去)。
 * 所以外壳挂上 `APP_CHROME`,弹窗的「点了外面」「按了 Esc」碰到它就当没发生(keepOpenOnAppChrome),焦点进出外壳
 * 不让弹窗的焦点圈套看见(installAppChromeGuards);内嵌网页视图亮着的时候,弹窗的遮罩连同它的滚动锁让开
 * (useEmbeddedViewUp,Dialog / Sheet / AlertDialog 的 Content 照它决定画不画遮罩)。
 *
 * 全屏看图的灯箱(components/app/image-preview 的宿主)也挂它:它同样盖在弹窗上面、又在弹窗外面 —— 在大图上翻页、
 * 点关闭,不该顺手把底下那个弹窗关掉。
 */
import * as React from "react";

export const APP_CHROME = { "data-app-chrome": "" } as const;

/**
 * 内嵌网页视图此刻亮着没有(主进程的 onViewState)。
 *
 * 亮着时原生视图盖住了 Mosael 的整个界面:底下开着的弹窗看不见,它的遮罩也看不见 —— 遮罩这时唯一还在起作用的是它带着的
 * **滚动锁**,而锁住的恰好是盖在上面、能看见的外壳(滚轮在外壳里被拦下)。所以亮着时弹窗不画遮罩;弹窗本身(内容、
 * 状态、焦点)原样留着,回来时遮罩重新铺上、滚动锁重新上。为什么不把弹窗改成非模态:Radix 换 modal 会把内容整棵重挂,
 * 回来时工作流库停在哪一张、焦点落回哪个按钮都没了。
 */
let viewUp = false;
const viewListeners = new Set<() => void>();
let stopWatchingView: (() => void) | null = null;

function subscribeViewUp(listener: () => void): () => void {
  if (!stopWatchingView && typeof window !== "undefined" && typeof window.mosaelPublish?.onViewState === "function") {
    stopWatchingView = window.mosaelPublish.onViewState((state) => {
      if (state.visible === viewUp) return;
      viewUp = state.visible;
      for (const one of viewListeners) one();
    });
  }
  viewListeners.add(listener);
  return () => viewListeners.delete(listener);
}

export function useEmbeddedViewUp(): boolean {
  return React.useSyncExternalStore(subscribeViewUp, () => viewUp, () => false);
}

/** 测试用:忘掉看到过的视图状态和订阅(下一个测试换一座桥)。 */
export function resetEmbeddedViewWatch(): void {
  stopWatchingView?.();
  stopWatchingView = null;
  viewUp = false;
  viewListeners.clear();
}

type OutsideEvent = Event & { detail?: { originalEvent?: Event } | number };

/**
 * 按下那一刻在外壳里的元素。Radix 的 Dialog 把「点了外面」推迟到 click 才判(deferPointerDownOutside),判的是按下的那个
 * 元素 —— 而那时它可能已经被这一下点击卸掉了:工作台「应用」面板里勾一项放进表单,那一行就没了;「装上」换成就地确认。
 * 脱离了文档的元素查不出它曾经在外壳里,弹窗就被当成点了外面关掉(工作台里勾一项,底下的工作流库没了)。所以按下时记一笔。
 */
const pressedInChrome = new WeakSet<EventTarget>();
let trackedDocument: Document | null = null;

function trackPresses(doc: Document | undefined) {
  if (!doc || trackedDocument === doc) return;
  trackedDocument = doc;
  doc.addEventListener(
    "pointerdown",
    (event) => {
      if (event.target instanceof Element && event.target.closest("[data-app-chrome]")) pressedInChrome.add(event.target);
    },
    true,
  );
}

const inChrome = (target: EventTarget | null | undefined) =>
  target instanceof Element && (target.closest("[data-app-chrome]") !== null || pressedInChrome.has(target));

/** 包一层弹窗的 onInteractOutside / onEscapeKeyDown:发生在窗口外壳上就拦下,别的照旧交给调用方给的那个。 */
export function keepOpenOnAppChrome<E extends OutsideEvent>(handler?: (event: E) => void) {
  trackPresses(typeof document === "undefined" ? undefined : document);
  return (event: E) => {
    const detail = typeof event.detail === "object" ? event.detail : undefined;
    const target = detail?.originalEvent?.target ?? event.target;
    if (inChrome(target)) {
      event.preventDefault();
      return;
    }
    handler?.(event);
  };
}

/**
 * 焦点进出窗口外壳时,不让模态弹窗的焦点圈套看见。
 *
 * Radix 的 FocusScope 在 document 上听 focusin / focusout(冒泡阶段):焦点跑到圈外就拽回来。在 body 上(React 的
 * 根之后、document 之前)把「落进外壳」「从圈里跑进外壳」的这两种事件拦住 —— 外壳自己的 onFocus 照常收到
 * (React 在根上听),圈套收不到。返回拆掉它的函数。
 */
export function installAppChromeGuards(doc: Document): () => void {
  const body = doc.body;
  const onFocusIn = (event: FocusEvent) => {
    if (inChrome(event.target)) event.stopPropagation();
  };
  const onFocusOut = (event: FocusEvent) => {
    if (inChrome(event.relatedTarget)) event.stopPropagation();
  };
  body.addEventListener("focusin", onFocusIn);
  body.addEventListener("focusout", onFocusOut);
  return () => {
    body.removeEventListener("focusin", onFocusIn);
    body.removeEventListener("focusout", onFocusOut);
  };
}
