"use client";

/**
 * 社区列表:搜索 + 标签 + 排序 + 卡片网格 + 加载更多。
 *
 * 第一页在服务端按 URL 里的 `?q&tag&sort` 取好交进来(可分享、可收藏、搜索引擎看得到);
 * 改筛选就改 URL,让服务端重新取。往后翻页用游标(ADR:`?cursor=…`)在浏览器里直接取
 * 同源的 `/api/community/v1/…`,接在后面。
 */
import { usePathname, useRouter } from "next/navigation";
import { Search, X } from "lucide-react";
import * as React from "react";

import { GRID, PluginCard, WorkflowCard } from "@/components/community/cards";
import { BUTTON, Spinner, errorText } from "@/components/community/ui";
import type { Locale } from "@/i18n/config";
import { HTML_LANG } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { ENDPOINTS, browserUrl } from "@/lib/community/endpoints";
import { errorFromResponse, networkError } from "@/lib/community/errors";
import { SORT_KEYS, type ItemKind, type Page, type PluginSummary, type SortKey, type WorkflowSummary } from "@/lib/community/types";
import { cn } from "@/lib/utils";

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        active ? "border-foreground bg-foreground text-background" : "border-border bg-card text-muted-foreground hover:border-foreground/30 hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export type BrowseQuery = { q: string; tag: string; sort: SortKey };

type Item = WorkflowSummary | PluginSummary;

/** 公开的列表不带令牌:同源 fetch,和服务端取第一页是同一个接口。 */
async function fetchPage(kind: ItemKind, query: BrowseQuery, cursor: string, locale: Locale): Promise<Page<Item>> {
  let response: Response;
  try {
    response = await fetch(browserUrl(ENDPOINTS.items.list(kind, { ...query, cursor })), {
      headers: { Accept: "application/json", "Accept-Language": HTML_LANG[locale] },
    });
  } catch {
    throw networkError();
  }
  if (!response.ok) throw await errorFromResponse(response);
  return (await response.json()) as Page<Item>;
}

export function ItemBrowser({ locale, kind, query, initial }: { locale: Locale; kind: ItemKind; query: BrowseQuery; initial: Page<Item> }) {
  const t = getMessages(locale);
  const router = useRouter();
  const pathname = usePathname();
  const [text, setText] = React.useState(query.q);
  const [items, setItems] = React.useState(initial.items);
  const [cursor, setCursor] = React.useState(initial.next_cursor);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [pending, startTransition] = React.useTransition();

  // 换了筛选,服务端交来新的第一页:接着翻的那几页作废。在渲染里对比而不是用 key 重挂 ——
  // 重挂会让正在打字的搜索框丢焦点。
  const [shown, setShown] = React.useState(initial);
  if (shown !== initial) {
    setShown(initial);
    setItems(initial.items);
    setCursor(initial.next_cursor);
    setError(null);
  }

  const navigate = React.useCallback(
    (next: Partial<BrowseQuery>) => {
      const merged = { ...query, ...next };
      const params = new URLSearchParams();
      if (merged.q.trim()) params.set("q", merged.q.trim());
      if (merged.tag) params.set("tag", merged.tag);
      if (merged.sort !== "trending") params.set("sort", merged.sort);
      const search = params.toString();
      startTransition(() => router.replace(search ? `${pathname}?${search}` : pathname, { scroll: false }));
    },
    [query, pathname, router],
  );

  // 打字停下 400ms 再搜:每敲一个字就换一次 URL、跑一次服务端,既浪费也会让输入框跟着抖。
  React.useEffect(() => {
    if (text === query.q) return;
    const timer = window.setTimeout(() => navigate({ q: text }), 400);
    return () => window.clearTimeout(timer);
  }, [text, query.q, navigate]);

  const loadMore = async () => {
    if (!cursor) return;
    setLoading(true);
    setError(null);
    try {
      const page = await fetchPage(kind, query, cursor, locale);
      setItems((current) => [...current, ...page.items]);
      setCursor(page.next_cursor);
    } catch (caught) {
      setError(errorText(caught, t.community.genericError, t.community.networkError));
    } finally {
      setLoading(false);
    }
  };

  // 标签从已经取到的条目里汇总:服务没有单独的标签接口,而当前在筛的那个标签要一直在。
  const tags = [...new Set([query.tag, ...items.flatMap((item) => item.tags)].filter(Boolean))].slice(0, 16);
  const placeholder = kind === "workflow" ? t.workflows.search : t.plugins.search;
  const filtered = Boolean(query.q || query.tag);

  return (
    <div className="grid gap-6" aria-busy={pending || undefined}>
      <div className="grid gap-3">
        <div className="flex flex-wrap items-center gap-3">
          {/* 窄屏独占一行:和筛选按钮挤在一行时会被压成一个图标宽。 */}
          <label className="relative block min-w-0 basis-full sm:max-w-md sm:flex-1 sm:basis-0">
            <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <input
              type="search"
              value={text}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") navigate({ q: text });
              }}
              placeholder={placeholder}
              aria-label={placeholder}
              className="h-11 w-full rounded-xl border border-input bg-card pr-4 pl-10 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-primary focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-primary/20"
            />
          </label>
          <fieldset className="m-0 flex min-w-0 flex-wrap gap-2 border-0 p-0">
            <legend className="sr-only">{t.community.sortLabel}</legend>
            {SORT_KEYS.map((sort) => (
              <Chip key={sort} active={query.sort === sort} onClick={() => navigate({ sort })}>
                {t.community.sort[sort]}
              </Chip>
            ))}
          </fieldset>
          {pending && <Spinner className="text-muted-foreground" />}
        </div>
        {tags.length > 0 && (
          <fieldset className="m-0 flex flex-wrap items-center gap-1.5 border-0 p-0">
            <legend className="sr-only">{t.community.tagsLabel}</legend>
            {tags.map((tag) => (
              <button
                key={tag}
                type="button"
                aria-pressed={query.tag === tag}
                onClick={() => navigate({ tag: query.tag === tag ? "" : tag })}
                className={cn(
                  "rounded-full px-2.5 py-1 text-xs transition-colors",
                  query.tag === tag ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground hover:text-foreground",
                )}
              >
                #{tag}
              </button>
            ))}
            {filtered && (
              <button
                type="button"
                onClick={() => {
                  setText("");
                  navigate({ q: "", tag: "" });
                }}
                className="inline-flex items-center gap-1 px-2 text-xs text-muted-foreground hover:text-foreground"
              >
                <X className="size-3.5" aria-hidden />
                {t.community.clear}
              </button>
            )}
          </fieldset>
        )}
      </div>

      {items.length > 0 ? (
        <ul className={cn(GRID, pending && "opacity-60 transition-opacity")}>
          {items.map((item) => (
            <li key={item.slug} className="grid">
              {kind === "workflow" ? (
                <WorkflowCard locale={locale} item={item as WorkflowSummary} />
              ) : (
                <PluginCard locale={locale} item={item as PluginSummary} />
              )}
            </li>
          ))}
        </ul>
      ) : (
        <div className="grid place-items-center gap-3 rounded-2xl border border-dashed border-border px-6 py-20 text-center">
          <Search className="size-6 text-muted-foreground" aria-hidden />
          <p className="m-0 font-semibold">{filtered ? t.community.empty : t.community.nothingYet}</p>
          {filtered && <p className="m-0 text-sm text-muted-foreground">{t.community.emptyHint}</p>}
        </div>
      )}

      {error && <p className="m-0 text-center text-sm text-destructive">{error}</p>}
      {cursor && (
        <div className="flex justify-center">
          <button type="button" onClick={() => void loadMore()} disabled={loading} className={BUTTON.secondary}>
            {loading && <Spinner />}
            {loading ? t.community.loading : t.community.loadMore}
          </button>
        </div>
      )}
    </div>
  );
}
