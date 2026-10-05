import React from "react";

/**
 * 清单末尾的那条线进了视野(提前 `marginPx`)就叫一声 —— 一页页从服务端取的清单(素材库)靠它接着取下一页。
 *
 * 交回一个 ref,挂在清单最后的一个元素上。`onReachEnd` 不给就是没有下一页了,不盯。
 * 用 IntersectionObserver,不在每次滚动时自己量;清单变长之后重新盯一次(线被推下去了,要等它再进来)。
 */
export function useReachEnd<T extends HTMLElement>(onReachEnd: (() => void) | undefined, length: number, marginPx = 240) {
  const line = React.useRef<T | null>(null);
  const callback = React.useRef(onReachEnd);
  callback.current = onReachEnd;
  const watching = Boolean(onReachEnd);
  React.useEffect(() => {
    const target = line.current;
    if (!watching || !target || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) callback.current?.();
      },
      { rootMargin: `${marginPx}px` },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [watching, length, marginPx]);
  return line;
}
