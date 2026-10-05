import * as React from "react";

/**
 * Mosael 自己的**整窗浮层**(看大图)亮着时,请主进程把前台的原生网页视图挪到窗口外,收起时放回(electron 的
 * accountViews:ForegroundHideReason 的 `overlay`)。
 *
 * 原生视图盖在一切 DOM 上:内嵌浏览器、ComfyUI 工作台亮着时打开大图,整窗的浮层只露得出顶栏和侧栏那几条,图被画布
 * 盖住。挪开(不是藏起来)的视图照常出帧,放回时就是它此刻的样子;顶栏、侧栏里的悬停说明走的是另一层(浮层视图),
 * 不受影响。
 *
 * 引用计数:几处浮层同时亮着,最后一处收起才放回。没有内嵌视图亮着时主进程那边只是记一笔,什么都不挪;网页版没有这座桥。
 */
let holders = 0;

function signal(up: boolean): void {
  const bridge = typeof window === "undefined" ? undefined : window.mosaelPublish;
  if (typeof bridge?.setOverlay !== "function") return;
  void bridge.setOverlay(up).catch(() => undefined);
}

/** 占住一次「让开」;返回放开它的函数(放多次只算一次)。 */
export function stepNativeViewAside(): () => void {
  holders += 1;
  if (holders === 1) signal(true);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    holders -= 1;
    if (holders === 0) signal(false);
  };
}

/**
 * 这会儿有整窗的浮层把原生视图挪开了没有。挪开时窗口里看得见的全是 Mosael 的 DOM:按键该交给浮层(大图的 Esc、左右翻页),
 * 不该再当成「落在看不见的地方」吞掉、交给网页(见 browser-pool/embeddedFocus)。
 */
export const nativeViewAside = () => holders > 0;

/** `active` 为真的这段时间里让原生视图让开(卸载时也放开)。 */
export function useNativeViewAside(active: boolean): void {
  React.useEffect(() => (active ? stepNativeViewAside() : undefined), [active]);
}
