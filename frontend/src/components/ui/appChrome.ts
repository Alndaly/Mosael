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
 * 所以外壳挂上 `APP_CHROME`,弹窗的「点了外面」「按了 Esc」碰到它就当没发生(keepOpenOnAppChrome),焦点进出外壳
 * 不让弹窗的焦点圈套看见(installAppChromeGuards)。
 */
export const APP_CHROME = { "data-app-chrome": "" } as const;

type OutsideEvent = Event & { detail?: { originalEvent?: Event } | number };

const inChrome = (target: EventTarget | null | undefined) => target instanceof Element && target.closest("[data-app-chrome]") !== null;

/** 包一层弹窗的 onInteractOutside / onEscapeKeyDown:发生在窗口外壳上就拦下,别的照旧交给调用方给的那个。 */
export function keepOpenOnAppChrome<E extends OutsideEvent>(handler?: (event: E) => void) {
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
