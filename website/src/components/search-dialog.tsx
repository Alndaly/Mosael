"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { createPortal } from "react-dom";

import type { Locale } from "@/i18n/config";
import type { SearchEntry } from "@/lib/search";
import { cn } from "@/lib/utils";

type Labels = {
  search: string;
  placeholder: string;
  empty: string;
  hint: string;
  close: string;
};

/** 命中一条的得分。标题 > 小节标题 > 正文 —— 搜「工作流」时那一页本身该排在提到它的段落前面。 */
function score(entry: SearchEntry, query: string): number {
  const title = entry.title.toLowerCase();
  const heading = entry.heading.toLowerCase();
  const body = entry.body.toLowerCase();
  let total = 0;
  if (title.includes(query)) total += title.startsWith(query) ? 120 : 80;
  if (heading.includes(query)) total += heading.startsWith(query) ? 60 : 40;
  if (body.includes(query)) total += 10;
  return total;
}

/** 命中处前后各截一段,让人一眼看出为什么搜到它。 */
function excerpt(body: string, query: string): string {
  const at = body.toLowerCase().indexOf(query);
  if (at < 0) return body.slice(0, 90);
  const from = Math.max(0, at - 30);
  return (from > 0 ? "…" : "") + body.slice(from, from + 110) + (from + 110 < body.length ? "…" : "");
}

/**
 * 把命中的字标出来。
 *
 * 按大小写不敏感切分,但**回显原文的那一段**而不是回显 query —— 否则搜 "mcp" 时结果里
 * 会把原文的 "MCP" 显示成小写。
 *
 * 选中那一行整条底色就是朱红,再往上叠一层半透明的朱红等于什么都没标出来。所以选中行改用
 * **反相**:纸色底 + 朱红字,在橙底上比任何一种"更深一点的橙"都好认。
 */
function Highlight({ text, query, active }: { text: string; query: string; active: boolean }) {
  if (!query) return <>{text}</>;
  const parts: React.ReactNode[] = [];
  const haystack = text.toLowerCase();
  let cursor = 0;
  for (let at = haystack.indexOf(query); at >= 0; at = haystack.indexOf(query, cursor)) {
    if (at > cursor) parts.push(text.slice(cursor, at));
    parts.push(
      <mark
        key={at}
        className={cn(
          "rounded-sm px-0.5 font-bold",
          active ? "bg-primary-foreground text-flame" : "bg-flame/20 text-foreground",
        )}
      >
        {text.slice(at, at + query.length)}
      </mark>,
    );
    cursor = at + query.length;
  }
  parts.push(text.slice(cursor));
  return <>{parts}</>;
}

/**
 * 文档全文搜索。
 *
 * 索引是构建期生成的静态 JSON(`/<语言>/search.json`),**打开对话框时才去取** —— 它比整站
 * 的 JS 还大,而多数访客根本不会搜。取回来存在 ref 里,一次会话只取一次。
 *
 * 中文不做分词:子串匹配对中文本来就够用(「工作流」直接命中),而引一个分词库进来要多下
 * 几百 KB 词典,换不回多少召回。
 */
export function SearchDialog({ locale, labels }: { locale: Locale; labels: Labels }) {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [entries, setEntries] = React.useState<SearchEntry[] | null>(null);
  const [active, setActive] = React.useState(0);
  const loaded = React.useRef(false);
  const listRef = React.useRef<HTMLUListElement>(null);

  // ⌘K / Ctrl+K 打开。装在 window 上而不是某个输入框上 —— 它是全站快捷键。
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((value) => !value);
      }
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  React.useEffect(() => {
    if (!open || loaded.current) return;
    loaded.current = true;
    fetch(`/${locale}/search.json`)
      .then((response) => response.json())
      .then(setEntries)
      .catch(() => {
        // 取不到就让它保持空:搜索框还在,只是搜不出东西,总比整页报错好。
        loaded.current = false;
      });
  }, [open, locale]);

  const results = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle || !entries) return [];
    return entries
      .map((entry) => ({ entry, value: score(entry, needle) }))
      .filter((item) => item.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 12)
      .map((item) => item.entry);
  }, [entries, query]);

  React.useEffect(() => setActive(0), [query]);

  /**
   * 开着的时候锁住页面滚动。
   *
   * 不锁的话,在结果列表里滚到底继续滚,滚动会**穿透**到后面的页面 —— 关掉对话框才发现
   * 整页已经跑到别处去了。列表自己再加 `overscroll-contain`,把这条链在列表边界就掐断。
   *
   * 锁的是 `<html>` 而**不是** `<body>`:这个站的滚动容器是文档元素,锁 body 没有任何效果
   * (试过,滚动照样穿透)。同时补上滚动条那几像素的内边距 —— 否则条一消失,整页会往右
   * 跳一下,弹窗背后的版面跟着抖。
   */
  React.useEffect(() => {
    if (!open) return;
    const root = document.documentElement;
    const gap = window.innerWidth - root.clientWidth;
    const overflow = root.style.overflow;
    const padding = root.style.paddingRight;
    root.style.overflow = "hidden";
    if (gap > 0) root.style.paddingRight = `${gap}px`;
    return () => {
      root.style.overflow = overflow;
      root.style.paddingRight = padding;
    };
  }, [open]);

  const needle = query.trim().toLowerCase();

  const go = React.useCallback(
    (entry: SearchEntry) => {
      setOpen(false);
      setQuery("");
      router.push(entry.href);
    },
    [router],
  );

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={labels.search}
        aria-label={labels.search}
        className="inline-flex h-9 items-center gap-2 rounded-lg px-2.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
      >
        <Search className="size-4" />
        {/* 窄屏只留放大镜:顶栏那点宽度得留给导航。 */}
        <span className="hidden font-mono text-xs tracking-wider lg:inline">⌘K</span>
      </button>

      {open && createPortal(
        <div
          data-search-overlay
          className="fixed inset-0 z-100 flex items-start justify-center bg-ink/45 p-4 pt-[12vh]"
          onClick={() => setOpen(false)}
          role="presentation"
        >
          <div
            className="w-full max-w-2xl overflow-hidden rounded-2xl border border-border bg-paper"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
            aria-modal
            aria-label={labels.search}
          >
            <div className="flex items-center gap-3 border-b border-border px-4">
              <Search className="size-5 shrink-0" />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    setActive((index) => Math.min(index + 1, results.length - 1));
                  } else if (event.key === "ArrowUp") {
                    event.preventDefault();
                    setActive((index) => Math.max(index - 1, 0));
                  } else if (event.key === "Enter" && results[active]) {
                    event.preventDefault();
                    go(results[active]);
                  }
                }}
                placeholder={labels.placeholder}
                className="h-14 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground"
              />
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="shrink-0 font-mono text-xs tracking-wider text-muted-foreground uppercase hover:text-foreground"
              >
                Esc
              </button>
            </div>

            <ul ref={listRef} className="m-0 max-h-[60vh] list-none overflow-y-auto overscroll-contain p-0">
              {query.trim() === "" ? (
                <li className="m-0 px-4 py-8 text-center text-sm text-muted-foreground">{labels.hint}</li>
              ) : results.length === 0 ? (
                <li className="m-0 px-4 py-8 text-center text-sm text-muted-foreground">{labels.empty}</li>
              ) : (
                results.map((entry, index) => (
                  <li key={`${entry.href}-${index}`} className="m-0">
                    <button
                      type="button"
                      onMouseEnter={() => setActive(index)}
                      onClick={() => go(entry)}
                      className={cn(
                        "block w-full border-b border-border/70 px-4 py-3 text-left transition-colors",
                        index === active && "bg-primary text-primary-foreground",
                      )}
                    >
                      <p className="m-0 flex items-baseline gap-2">
                        <span className="font-display font-bold">
                          <Highlight text={entry.heading || entry.title} query={needle} active={index === active} />
                        </span>
                        <span
                          className={cn(
                            "font-mono text-[0.65rem] tracking-wider uppercase",
                            index === active ? "opacity-80" : "text-muted-foreground",
                          )}
                        >
                          {entry.section} · {entry.title}
                        </span>
                      </p>
                      {entry.body && (
                        <p
                          className={cn("m-0 mt-1 text-sm", index === active ? "opacity-90" : "text-muted-foreground")}
                        >
                          <Highlight text={excerpt(entry.body, needle)} query={needle} active={index === active} />
                        </p>
                      )}
                    </button>
                  </li>
                ))
              )}
            </ul>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
