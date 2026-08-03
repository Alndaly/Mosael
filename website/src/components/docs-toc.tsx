"use client";

import * as React from "react";

import type { TocEntry } from "@/lib/toc";
import { cn } from "@/lib/utils";

/**
 * 本页目录,带滚动定位。
 *
 * 用 IntersectionObserver 盯住正文里的每个标题,而不是在 scroll 事件里算位置 —— 后者每帧
 * 都要读一次 offsetTop,长文档上会明显掉帧。
 *
 * `rootMargin` 把视口上沿压到距顶 96px(站头高度),下沿抬到 70% 处:于是"当前小节"指的是
 * **刚滚过站头的那个标题**,而不是屏幕正中央碰巧撞上的那个。
 */
export function DocsToc({ entries, label, className }: { entries: TocEntry[]; label: string; className?: string }) {
  const [active, setActive] = React.useState<string | null>(entries[0]?.id ?? null);

  React.useEffect(() => {
    if (entries.length === 0) return;
    const nodes = entries.map((entry) => document.getElementById(entry.id)).filter((node) => node !== null);
    if (nodes.length === 0) return;

    const observer = new IntersectionObserver(
      (records) => {
        const visible = records.filter((record) => record.isIntersecting);
        if (visible.length === 0) return;
        // 同时有几个标题在窗口里时取最靠上的那个。
        const top = visible.reduce((a, b) => (a.boundingClientRect.top < b.boundingClientRect.top ? a : b));
        setActive(top.target.id);
      },
      { rootMargin: "-96px 0px -70% 0px", threshold: 0 },
    );
    nodes.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [entries]);

  if (entries.length === 0) return null;

  const list = (
    <ul className="m-0 list-none border-l-2 border-ink p-0">
      {entries.map((entry) => {
        const current = entry.id === active;
        return (
          <li key={entry.id} className="m-0">
            <a
              href={`#${entry.id}`}
              aria-current={current ? "location" : undefined}
              className={cn(
                "-ml-0.5 block border-l-2 py-1 transition-colors",
                entry.depth === 3 ? "pl-7" : "pl-4",
                current
                  ? "border-flame font-bold text-foreground"
                  : "border-transparent text-muted-foreground hover:border-ink hover:text-foreground",
              )}
            >
              {entry.text}
            </a>
          </li>
        );
      })}
    </ul>
  );

  return (
    <>
      {/* 窄屏折起来 —— 本页目录排在正文前面时是"这一页讲了什么"的摘要,但摊开十几行就成了
          一堵墙。桌面端它在右栏,不占正文的位置,照常展开。 */}
      <details className={cn("border-2 border-ink text-sm xl:hidden", className)}>
        <summary className="cursor-pointer list-none px-4 py-3 font-display font-bold tracking-tight">{label}</summary>
        <div className="border-t-2 border-ink px-4 py-3">{list}</div>
      </details>
      <nav aria-label={label} className={cn("hidden text-sm xl:block", className)}>
        <p className="m-0 mb-4 font-mono text-xs font-bold tracking-widest text-flame uppercase">{label}</p>
        {list}
      </nav>
    </>
  );
}
