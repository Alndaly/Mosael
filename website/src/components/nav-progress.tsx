"use client";

import * as React from "react";
import { usePathname } from "next/navigation";

/** 到 90% 就停住等真正加载完 —— 走满 100% 再等,比走到一半停更像卡死。 */
const CEILING = 90;

/**
 * 换页时顶部的那条进度。
 *
 * App Router 没有公开的路由事件,所以两头分别接:**开始**靠捕获阶段的链接点击,
 * **结束**靠 `usePathname()` 变化。这比去钩 router 内部稳 —— 那些是私有 API,升级就断。
 *
 * 站内跳转本身通常很快,所以延迟 120ms 才显形:一闪而过的进度条比没有更烦。
 * 另有一道 10 秒兜底,免得某次导航没走完就把条子永远留在屏幕上。
 */
export function NavProgress() {
  const pathname = usePathname();
  const [value, setValue] = React.useState(0);
  const [visible, setVisible] = React.useState(false);
  const timers = React.useRef<number[]>([]);

  const clearTimers = React.useCallback(() => {
    timers.current.forEach(window.clearTimeout);
    timers.current.forEach(window.clearInterval);
    timers.current = [];
  }, []);

  /** 收尾:定时器、显隐、进度一起归位。**必须一起** —— 只藏不停的话,条子在看不见的地方
   *  一直往前爬,下一次导航接着从半路开始。 */
  const stop = React.useCallback(() => {
    clearTimers();
    setVisible(false);
    setValue(0);
  }, [clearTimers]);

  const start = React.useCallback(() => {
    clearTimers();
    setValue(0);
    timers.current.push(
      window.setTimeout(() => {
        setVisible(true);
        setValue(15);
        // 越接近上限走得越慢 —— 匀速走到 90% 会让人以为"马上就好",然后干等。
        timers.current.push(
          window.setInterval(() => setValue((current) => current + Math.max(0.5, (CEILING - current) / 12)), 180),
        );
      }, 120),
    );
    // 兜底:某次导航没走完(比如目标 404 又被拦下),别把条子永远留在屏幕上。
    timers.current.push(window.setTimeout(stop, 10_000));
  }, [clearTimers, stop]);

  React.useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const anchor = (event.target as HTMLElement | null)?.closest?.("a");
      if (!anchor || anchor.target === "_blank" || anchor.hasAttribute("download")) return;
      const href = anchor.getAttribute("href");
      if (!href || href.startsWith("#")) return; // 锚点是原地跳,没有加载
      const next = new URL(anchor.href, location.href);
      if (next.origin !== location.origin) return;
      if (next.pathname === location.pathname) return; // 同一页,不会有加载
      start();
    };
    document.addEventListener("click", onClick, true);
    window.addEventListener("popstate", start);
    return () => {
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("popstate", start);
    };
  }, [start]);

  // 路径变了 = 新页面已经渲染,补满再淡出。
  React.useEffect(() => {
    clearTimers();
    setValue(100);
    const done = window.setTimeout(stop, 220);
    return () => window.clearTimeout(done);
  }, [pathname, clearTimers, stop]);

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-x-0 top-0 z-100 h-1 transition-opacity duration-200 motion-reduce:transition-none"
      style={{ opacity: visible ? 1 : 0 }}
    >
      <div
        className="h-full bg-flame transition-[width] duration-200 ease-out motion-reduce:transition-none"
        style={{ width: `${Math.min(value, 100)}%` }}
      />
    </div>
  );
}
