import React from "react";

/**
 * 一个元素此刻的内容宽度(随它变化跟着变)。传元素本身(由回调 ref 存进 state),不传 ref 对象 ——
 * 元素晚于组件挂上(先是骨架、数据到了才画出来)时,ref 对象变了没人知道。
 * 量不到(还没挂上、测试环境没有 ResizeObserver)时是 0,调用方拿 0 当「还不知道」处理。
 */
export function useElementWidth(element: HTMLElement | null): number {
  const [width, setWidth] = React.useState(0);
  React.useLayoutEffect(() => {
    if (!element) return;
    setWidth(element.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return width;
}
