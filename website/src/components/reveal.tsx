"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * 进场动画:上滑 + 淡入,只在元素第一次露面时跑一次。
 *
 * 用 IntersectionObserver 而不是滚动监听:后者每帧都要问一次位置,而这里只需要知道
 * "第一次露面"这一个瞬间 —— 观察到之后就把自己取消掉,滚回去不重播。
 *
 * 终态由 `data-shown` 触发,状态和样式都写在这一个 className 里,CSS 那边没有对应物。
 * `motion-reduce:` 那几条让开了"减少动态效果"的人直接看到终态,不做任何位移。
 */
export function Reveal({
  children,
  delay = 0,
  className,
  as: Tag = "div",
}: {
  children: React.ReactNode;
  /** 同一组里错开出场,单位毫秒。别超过 200,再多就变成"等页面加载"了。 */
  delay?: number;
  className?: string;
  as?: "div" | "section" | "article" | "li";
}) {
  const ref = React.useRef<HTMLElement>(null);

  React.useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        node.dataset.shown = "true";
        observer.disconnect();
      },
      // 元素露出一小截就开始 —— 等整块都进了视口才动,人已经读完了。
      { rootMargin: "0px 0px -12% 0px", threshold: 0.05 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <Tag
      ref={ref as never}
      style={{ transitionDelay: `${delay}ms` }}
      className={cn(
        "translate-y-6 opacity-0 transition-[opacity,transform] duration-700 ease-[cubic-bezier(0.16,1,0.3,1)]",
        "data-[shown=true]:translate-y-0 data-[shown=true]:opacity-100",
        "motion-reduce:translate-y-0 motion-reduce:opacity-100 motion-reduce:transition-none",
        className,
      )}
    >
      {children}
    </Tag>
  );
}
