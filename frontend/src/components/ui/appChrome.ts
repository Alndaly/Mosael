import type * as React from "react";
import { createPortal } from "react-dom";

/**
 * **窗口外壳**:内嵌网页视图亮着时盖在应用最上层的浏览器顶栏、页面列表、侧栏、框选浮层(App 的 PublishViewBar、
 * BrowserPageList、ToolDrawer、RegionOverlay)。
 *
 * 它们和底下开着的弹窗没有关系,却在弹窗外面。模态弹窗(Radix 的 Dialog / Sheet)会:
 * - 把点在外面的那一下当成「点了弹窗外面」,把弹窗关掉 —— 真机上就是这样:从工作流库打开内嵌的 ComfyUI 之后点
 *   「返回 Mosael」,回来工作流库没了,得重新打开、重新找到那一张;
 * - 把 body 设成 `pointer-events: none`,外壳跟着点不动(styles.css 给外壳放开);
 * - 把焦点圈在自己里面:点地址栏,焦点马上被拽回弹窗,一个字也打不进去;
 * - 按 Esc 就关:在地址栏按 Esc 想撤销输入,底下的弹窗关了。
 * - 锁住滚动:遮罩(Radix 的 Overlay 里那层 react-remove-scroll)在 document 上听 wheel / touchmove,落在弹窗外面的
 *   一律 preventDefault —— 外壳里能点、能悬停,滚轮却滚不动(工作台右边那一列:「应用」面板超出一屏,滚不下去)。
 * 所以外壳挂上 `APP_CHROME`,弹窗的「点了外面」「按了 Esc」碰到它就当没发生(keepOpenOnAppChrome),焦点进出外壳、
 * 外壳里的滚轮不让弹窗的焦点圈套和滚动锁看见(installAppChromeGuards)。外壳里打开的浮层(Popover / Select / 右键菜单)
 * 也是外壳(见 tooltip 的 useChromeLayer)。
 *
 * 弹窗的遮罩一直挂着,不因为内嵌网页视图亮着就卸掉:Radix 的 Dialog 给遮罩和内容各开一个 portal,卸掉的遮罩再挂回来
 * 时追加在 body 末尾、排到了内容**后面** —— 同一个 z,工作台「返回 Mosael」之后模糊盖在了弹窗上面。
 *
 * 全屏看图的灯箱(components/app/image-preview 的宿主)也挂它:它同样盖在弹窗上面、又在弹窗外面 —— 在大图上翻页、
 * 点关闭,不该顺手把底下那个弹窗关掉。右下角的提示条(App 的 AppToaster)也是:弹窗开着时点提示条上的「查看」,
 * 此前落在遮罩上,弹窗关了、「查看」没打开(ADR 0051 D40)。
 *
 * 顶栏(拖它挪窗口的那一条)还要排在底下那个弹窗**后面**,见 ChromeAboveDialogs。
 */
export const APP_CHROME = { "data-app-chrome": "" } as const;

/**
 * 把窗口外壳挂到 body 末尾 —— 排在**它出现时已经开着**的弹窗后面,拖得动窗口。
 *
 * 顶栏声明了 `-webkit-app-region: drag`。拖拽区是按**文档顺序**收集的(Chromium 的 LocalFrameView::CollectDraggableRegions
 * 先序遍历布局树,和 z-index 无关),Electron 合并时**后面的盖前面的**(shell/browser/ui/drag_util.cc:重叠处以排在后面的为准)。
 * 弹窗的遮罩(整窗)和内容都声明了 no-drag,经 Portal 挂在 body 末尾;顶栏要是留在应用的根节点里,就排在它们前面、被整块
 * 减掉 —— 真机上从工作流库「在工作台里打开」,工作流库留在底下,工作台的顶栏怎么拖窗口都不动。
 *
 * 挂到 body 末尾之后,文档顺序就是打开的先后:先开着的弹窗在前,顶栏盖过它;顶栏之后才打开的(看大图、工作台里的弹窗)在后、
 * 盖在顶栏上,和它们画在顶栏上面一致 —— 它们伸进顶栏那一截照样点得到。
 */
export function ChromeAboveDialogs({ children }: { children: React.ReactNode }): React.ReactPortal {
  return createPortal(children, document.body);
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
 * 焦点进出窗口外壳、外壳里的滚轮,不让模态弹窗的焦点圈套和滚动锁看见。
 *
 * Radix 的 FocusScope 在 document 上听 focusin / focusout(冒泡阶段):焦点跑到圈外就拽回来;遮罩的滚动锁同样在
 * document 上听 wheel / touchmove,落在弹窗外面的就 preventDefault。在 body 上(React 的根之后、document 之前)把
 * 「落进外壳」「从圈里跑进外壳」的焦点事件和外壳里的滚轮拦住 —— 外壳自己的 onFocus、onWheel 照常收到(React 在根上
 * 听),滚动照常发生,圈套和锁收不到。返回拆掉它的函数。
 */
export function installAppChromeGuards(doc: Document): () => void {
  const body = doc.body;
  const onFocusIn = (event: FocusEvent) => {
    if (inChrome(event.target)) event.stopPropagation();
  };
  const onFocusOut = (event: FocusEvent) => {
    if (inChrome(event.relatedTarget)) event.stopPropagation();
  };
  const onScroll = (event: Event) => {
    if (inChrome(event.target)) event.stopPropagation();
  };
  body.addEventListener("focusin", onFocusIn);
  body.addEventListener("focusout", onFocusOut);
  body.addEventListener("wheel", onScroll, { passive: true });
  body.addEventListener("touchmove", onScroll, { passive: true });
  return () => {
    body.removeEventListener("focusin", onFocusIn);
    body.removeEventListener("focusout", onFocusOut);
    body.removeEventListener("wheel", onScroll);
    body.removeEventListener("touchmove", onScroll);
  };
}
