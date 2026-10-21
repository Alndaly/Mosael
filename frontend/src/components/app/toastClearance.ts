import React from "react";

import { useNativeViewInFront } from "@/lib/nativeView";

/**
 * 提示条(右下角的 toast)让开页面底部固定的输入区。**机制保留备用 —— 当前没有任何输入区挂
 * `data-toast-avoid`**(维护者定):提示条就该待在窗口右下角,短暂盖住输入区一角没关系,抬起来反而飘在半空。
 * 后续要加新表面时再启用:贴底的输入区在最外层元素上挂回这个标记即可,这里量到它就自动让。
 *
 * **为什么留着这条规则**:维护者曾截图 —— AI Studio 里语音合成完,「语音合成 · 已完成」那一条正好盖在输入框右下角的发送键和
 * 「⌘Enter 生成」上。提示条固定在窗口右下角,而贴底输入区的右边缘落在提示条那一列里。
 *
 * **什么时候让**:输入区**挡掉那一列的大半**(横向压掉一半以上)才抬到它上沿之上,留 12px。只压到一个角不让 ——
 * 擦到 1px 也整体抬起来的话,一张 780px 居中、右缘只压进那一列 64px(18%)的输入卡,会把提示条抬到离底 164px:
 * 看着像飘在输入框上方,而不是它该在的右下角。
 *
 * **取舍**:压到一角时不动的代价是提示条会盖住输入区右端的一小条(发送键在那里)。宁可这样,也不要提示条离开右下角 ——
 * 提示条是给人「看一眼就走」的,发到半空既不像提示也不在预期位置;真挡到要紧处,再谈让法。
 *
 * **一条全局规则,不逐页挪**:贴底的输入区在最外层元素上挂 `data-toast-avoid`;新的贴底输入区只要挂上这个标记。
 * 棘轮 `design/toastClearance.test.ts` 盯着机制这一头别被拔掉。
 */
export const TOAST_AVOID_ATTRIBUTE = "data-toast-avoid";

/** Sonner 的默认值:离窗口边 24px(窄于 600px 时 16px),每条宽 356px。 */
export const TOAST_EDGE = 24;
const TOAST_EDGE_NARROW = 16;
const TOAST_WIDTH = 356;
const NARROW = 600;
/** 抬起来之后离输入区上沿留多少。 */
const TOAST_CLEARANCE = 12;
/** 输入区横向挡掉提示条这么大一截才算「挡着它了」。小于它就待在右下角。 */
const TOAST_BLOCKED_SHARE = 0.5;
/** 提示条在底边往上占的那一截(一条提示的高度上下):输入区伸进这一截才算挡着它。 */
const TOAST_BAND = 96;
type Box = Pick<DOMRect, "top" | "bottom" | "left" | "right" | "width" | "height">;

/**
 * 提示条离窗口底边该多远(px):右下角那一列里,被挂了标记的输入区挡掉大半的,抬到它上沿之上;否则就是默认的边距。
 * 抬到顶也给窗口留一截,不让提示条被顶出屏幕。
 */
export function toastBottomOffset(boxes: Box[], viewport: { width: number; height: number }): number {
  const edge = viewport.width < NARROW ? TOAST_EDGE_NARROW : TOAST_EDGE;
  const width = Math.min(TOAST_WIDTH, viewport.width - 2 * edge);
  const laneLeft = viewport.width - edge - width;
  const laneRight = viewport.width - edge;
  const bandTop = viewport.height - edge - TOAST_BAND;
  const blocked = width * TOAST_BLOCKED_SHARE;
  let offset = edge;
  for (const box of boxes) {
    if (box.width <= 0 || box.height <= 0) continue; // 藏着的(display: none、收起的面板里)
    if (box.right <= laneLeft || box.left >= laneRight) continue; // 不在右下角那一列
    if (box.bottom <= bandTop || box.top >= viewport.height) continue; // 在提示条上面,或者整个在窗口外
    const covered = Math.min(box.right, laneRight) - Math.max(box.left, laneLeft);
    if (covered < blocked) continue; // 只压到一角:照旧待在右下角
    offset = Math.max(offset, viewport.height - box.top + TOAST_CLEARANCE);
  }
  return Math.round(Math.min(offset, Math.max(edge, viewport.height - 120)));
}

/**
 * 给 Toaster 的 `offset` / `mobileOffset` 用:底边跟着挂了标记的输入区走。
 *
 * 什么时候重新量:窗口大小变了、DOM 里挂上 / 拿掉了输入区(换页、开关智能体面板)、输入区自己长高了(多写几行)、
 * 原生视图进出前台。一帧最多量一次 —— DOM 变动很频繁(流式回复一帧一变),回调只排一次 requestAnimationFrame;值没变不重渲。
 *
 * 原生视图(内嵌浏览器、工作台的画布)在前台时,提示条画在它上面(toastMirror),而页面整块在它底下:只认外壳里的输入区
 * (工作台右边那一列的智能体输入框),底下那页看不见的输入框不把提示条抬起来。
 */
export function useToastClearance(): number {
  const [offset, setOffset] = React.useState(TOAST_EDGE);
  const overNativeView = useNativeViewInFront();
  React.useEffect(() => {
    let frame = 0;
    const observed = new Set<Element>();
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => schedule());
    const measure = () => {
      frame = 0;
      const marked = Array.from(document.querySelectorAll(`[${TOAST_AVOID_ATTRIBUTE}]`)).filter(
        (element) => !overNativeView || element.closest("[data-app-chrome]") !== null,
      );
      if (resize) {
        for (const element of marked) {
          if (observed.has(element)) continue;
          resize.observe(element);
          observed.add(element);
        }
        for (const element of observed) {
          if (marked.includes(element)) continue;
          resize.unobserve(element);
          observed.delete(element);
        }
      }
      setOffset(toastBottomOffset(marked.map((element) => element.getBoundingClientRect()),
        { width: window.innerWidth, height: window.innerHeight }));
    };
    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(measure);
    };
    const mutations = new MutationObserver(schedule);
    mutations.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: [TOAST_AVOID_ATTRIBUTE] });
    window.addEventListener("resize", schedule);
    schedule();
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      mutations.disconnect();
      resize?.disconnect();
      window.removeEventListener("resize", schedule);
    };
  }, [overNativeView]);
  return offset;
}
