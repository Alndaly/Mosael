"use client";

import Link from "next/link";
import {
  AlertCircle,
  BadgeCheck,
  Bookmark,
  Download,
  Heart,
  LoaderCircle,
  MessageSquare,
  RotateCcw,
  Search,
  Upload,
  X,
} from "lucide-react";
import * as React from "react";

import { ShareListSkeleton } from "@/components/community/share-skeleton";
import { InitialTile } from "@/components/community/tile";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { toPlainText } from "@/lib/inline-markdown";
import { CloudApiError, cloudShares, type CloudShare, type CloudShareKind, type CloudSharePage } from "@/lib/cloud";
import { cn } from "@/lib/utils";

import { SHARE_PAGE_SIZE, shareSearch, type ShareListQuery } from "./share-utils";

const CARD =
  "group flex min-w-0 flex-col rounded-2xl border border-border bg-card p-5 transition-[border-color,transform,box-shadow] hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-[0_10px_30px_-18px_color-mix(in_oklab,var(--primary)_60%,transparent)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring motion-reduce:transition-none motion-reduce:hover:translate-y-0";

const GRID = "m-0 grid list-none grid-cols-[minmax(0,1fr)] gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3";

function errorText(locale: Locale, failure: unknown): string {
  const t = getMessages(locale).community;
  return failure instanceof CloudApiError ? failure.text(locale) : t.loadFailed;
}

function sameQuery(a: ShareListQuery, b: ShareListQuery): boolean {
  return a.q === b.q && a.kind === b.kind && a.sort === b.sort;
}

function Stat({ icon: Icon, label, value }: { icon: typeof Download; label: string; value: number }) {
  return (
    <span className="inline-flex items-center gap-1.5" title={label}>
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span className="sr-only">{label}</span>
      <span className="font-mono tabular-nums">{value}</span>
    </span>
  );
}

/**
 * 一张分享卡:作者(首字母色块头像 + 昵称)、标题、摘要、类型、四项统计。
 *
 * 作者名只用 `display_name` —— 后端公开响应里也只有 `display_name` / `handle` /
 * `avatar_seed` 三列,公开页面连邮箱的边都碰不到。
 */
export function ShareCard({ locale, share }: { locale: Locale; share: CloudShare }) {
  const t = getMessages(locale).community;
  const name = share.author.display_name?.trim() || share.author.handle || "—";
  const summary = share.summary?.trim() ? toPlainText(share.summary) : "";
  // 官方插件分享也要说清是「插件」,不能因为原先把 board 以外的都当工作流而标错。
  const kindLabel: Record<CloudShareKind, string> = {
    workflow: t.kindWorkflow,
    board: t.kindBoard,
    plugin: t.kindPlugin,
  };
  return (
    <Link href={localePath(locale, `/community/${share.id}`)} className={CARD}>
      <div className="flex min-w-0 items-center gap-3.5">
        <InitialTile seed={share.author.avatar_seed || share.author.handle || share.id} name={name} size="md" />
        <div className="grid min-w-0 gap-0.5">
          <h3 className="m-0 line-clamp-2 text-base font-semibold tracking-tight group-hover:text-primary">{share.title}</h3>
          <span className="inline-flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
            <span className="truncate">{name}</span>
            {share.author.official && (
              <span className="inline-flex shrink-0 items-center gap-0.5 font-medium text-primary">
                <BadgeCheck className="size-3.5" aria-hidden />
                {t.official}
              </span>
            )}
            <span aria-hidden> · </span>
            <span className="shrink-0">{kindLabel[share.kind]}</span>
          </span>
        </div>
      </div>
      <p
        className={cn(
          "mt-4 mb-0 line-clamp-3 flex-1 text-sm leading-6",
          summary ? "text-muted-foreground" : "text-muted-foreground/70",
        )}
      >
        {summary || t.noSummary}
      </p>
      <div className="mt-5 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-border pt-4 text-xs text-muted-foreground">
        <Stat icon={Download} label={t.downloads} value={share.stats.downloads} />
        <Stat icon={Heart} label={t.likes} value={share.stats.likes} />
        <Stat icon={Bookmark} label={t.favorites} value={share.stats.favorites} />
        <Stat icon={MessageSquare} label={t.comments} value={share.stats.comments} />
      </div>
    </Link>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        active
          ? "border-foreground bg-foreground text-background"
          : "border-border bg-card text-muted-foreground hover:border-foreground/30 hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

/**
 * 空态:两行字 + 一个按钮。
 *
 * 早先是一个占满整屏的大虚线框:图标 + 三行说明 + 按钮。列表空是个很普通的状态,不该比
 * 列表本身还占地方,所以收成一个紧凑的块 —— 一行说清是什么状态,一行给下一步,一个按钮。
 *
 * 按钮分两种,但**永远只有一个**:没有数据时是「去上传」(页头此时不给 CTA),筛空时是
 * 「清除筛选」。两种情况下「去上传」都不会重复出现。
 */
function EmptyState({ locale, filtered, onClear }: { locale: Locale; filtered: boolean; onClear: () => void }) {
  const t = getMessages(locale).community;
  return (
    <div className="rounded-xl border border-border bg-card px-5 py-6">
      <p className="m-0 text-sm font-semibold">{filtered ? t.emptyFiltered : t.emptyNoShares}</p>
      <p className="m-0 mt-1 text-sm leading-6 text-muted-foreground">
        {filtered ? t.emptyFilteredHint : t.emptyNoSharesHint}
      </p>
      {filtered ? (
        <button
          type="button"
          onClick={onClear}
          className="mt-4 inline-flex h-9 items-center rounded-full border border-border px-4 text-sm font-semibold transition-colors hover:border-primary/50 hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          {t.clearFilters}
        </button>
      ) : (
        <Link
          href={localePath(locale, "/community/upload")}
          className="mt-4 inline-flex min-h-10 items-center gap-1.5 rounded-full bg-primary px-4 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/88"
        >
          <Upload className="size-4" aria-hidden />
          {t.uploadCta}
        </Link>
      )}
    </div>
  );
}

/**
 * 社区列表:服务端给第一页,之后搜索 / 筛选 / 排序 / 翻页都在浏览器里向同一个
 * `cloudShares.list` 取。筛选条件同步到地址栏(replaceState,不触发服务端导航),
 * 刷新或分享出去的链接仍然能打开同一份结果。
 */
export function ShareBrowser({
  locale,
  initial,
  initialError,
  initialQuery,
}: {
  locale: Locale;
  initial: CloudSharePage | null;
  initialError: string;
  initialQuery: ShareListQuery;
}) {
  const t = getMessages(locale).community;
  const [query, setQuery] = React.useState<ShareListQuery>(initialQuery);
  const [items, setItems] = React.useState<CloudShare[]>(initial?.items ?? []);
  const [nextCursor, setNextCursor] = React.useState<string | null>(initial?.next_cursor ?? null);
  const [error, setError] = React.useState(initialError);
  const [busy, setBusy] = React.useState(false);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const lastFetched = React.useRef<ShareListQuery>(initialQuery);
  const ticket = React.useRef(0);

  const fetchFirst = React.useCallback(
    async (next: ShareListQuery) => {
      const current = ++ticket.current;
      setBusy(true);
      setError("");
      try {
        const page = await cloudShares.list({
          q: next.q,
          kind: next.kind || undefined,
          sort: next.sort,
          limit: SHARE_PAGE_SIZE,
        });
        if (current !== ticket.current) return;
        setItems(page.items);
        setNextCursor(page.next_cursor);
      } catch (failure) {
        if (current !== ticket.current) return;
        setItems([]);
        setNextCursor(null);
        setError(errorText(locale, failure));
      } finally {
        if (current === ticket.current) setBusy(false);
      }
    },
    [locale],
  );

  // 输入停顿 320ms 再查;浏览器里换筛选项时不走服务端导航,地址栏只做 replaceState。
  React.useEffect(() => {
    if (sameQuery(lastFetched.current, query)) return;
    const timer = window.setTimeout(() => {
      lastFetched.current = query;
      void fetchFirst(query);
    }, 320);
    return () => window.clearTimeout(timer);
  }, [fetchFirst, query]);

  React.useEffect(() => {
    // 地址栏就地改(replaceState):不触发服务端导航,列表由下面的请求就地更新。
    // 查询串的拼法在 share-utils 里,首屏解析用的是同一对函数 —— 刷新后结果一致。
    window.history.replaceState(null, "", localePath(locale, "/community") + shareSearch(query));
  }, [locale, query]);

  const loadMore = async () => {
    if (!nextCursor || loadingMore || busy) return;
    setLoadingMore(true);
    setError("");
    const requested = query;
    try {
      const page = await cloudShares.list({
        q: requested.q,
        kind: requested.kind || undefined,
        sort: requested.sort,
        limit: SHARE_PAGE_SIZE,
        cursor: nextCursor,
      });
      if (!sameQuery(requested, lastFetched.current)) return;
      setItems((previous) => [...previous, ...page.items]);
      setNextCursor(page.next_cursor);
    } catch (failure) {
      setError(errorText(locale, failure));
    } finally {
      setLoadingMore(false);
    }
  };

  const filtered = query.q.trim() !== "" || query.kind !== "";
  const retry = () => {
    lastFetched.current = query;
    void fetchFirst(query);
  };

  return (
    <div className="grid gap-6">
      <div className="grid gap-4">
        <label className="relative block min-w-0 sm:max-w-md">
          <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <input
            type="search"
            value={query.q}
            onChange={(event) => setQuery((previous) => ({ ...previous, q: event.target.value }))}
            placeholder={t.searchShares}
            aria-label={t.searchShares}
            className="h-11 w-full rounded-xl border border-input bg-card pr-4 pl-10 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-primary focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-primary/20"
          />
        </label>

        {/*
         * 类型和排序是**两个维度**,不是一排可以混着选的 chip:早先 `[全部][工作流][画布]
         * [最新][热门]` 挤在同一个 flex 行里,看着像「五选一」。现在各成一个带标题的
         * fieldset,中间用竖线隔开、留出间距 —— 选类型不影响排序,选排序也不影响类型。
         */}
        <div className="flex flex-wrap items-end gap-x-8 gap-y-4">
          <fieldset className="m-0 min-w-0 border-0 p-0">
            <legend className="mb-2 p-0 font-mono text-[0.6875rem] font-bold tracking-widest text-muted-foreground uppercase">
              {t.filterKind}
            </legend>
            <div className="flex flex-wrap gap-2">
              <Chip active={query.kind === ""} onClick={() => setQuery((previous) => ({ ...previous, kind: "" }))}>
                {t.all}
              </Chip>
              <Chip
                active={query.kind === "workflow"}
                onClick={() => setQuery((previous) => ({ ...previous, kind: "workflow" }))}
              >
                {t.kindWorkflow}
              </Chip>
              <Chip active={query.kind === "board"} onClick={() => setQuery((previous) => ({ ...previous, kind: "board" }))}>
                {t.kindBoard}
              </Chip>
            </div>
          </fieldset>

          {/* 竖线 = 两个控件之间的分隔;`hr` 自带 separator 语义,不用 span + role。 */}
          <hr
            aria-orientation="vertical"
            className="mb-2.5 hidden h-9 w-px shrink-0 self-end border-0 bg-border sm:block"
          />

          <fieldset className="m-0 min-w-0 border-0 p-0">
            <legend className="mb-2 p-0 font-mono text-[0.6875rem] font-bold tracking-widest text-muted-foreground uppercase">
              {t.filterSort}
            </legend>
            <div className="flex flex-wrap gap-2">
              <Chip active={query.sort === "new"} onClick={() => setQuery((previous) => ({ ...previous, sort: "new" }))}>
                {t.sortNew}
              </Chip>
              <Chip active={query.sort === "hot"} onClick={() => setQuery((previous) => ({ ...previous, sort: "hot" }))}>
                {t.sortHot}
              </Chip>
            </div>
          </fieldset>

          {(filtered || query.q) && (
            <button
              type="button"
              onClick={() => setQuery({ q: "", kind: "", sort: "new" })}
              className="mb-0.5 ms-auto inline-flex h-9 items-center gap-1 rounded-full px-2 text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              <X className="size-4" aria-hidden />
              {t.clearFilters}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1">{error}</span>
          <button
            type="button"
            onClick={retry}
            className="inline-flex items-center gap-1.5 rounded-full border border-destructive/40 px-3 py-1.5 font-semibold hover:bg-destructive/10"
          >
            <RotateCcw className="size-3.5" aria-hidden />
            {t.retry}
          </button>
        </div>
      )}

      {busy ? (
        <ShareListSkeleton locale={locale} />
      ) : items.length > 0 ? (
        <>
          <ul className={GRID}>
            {items.map((share) => (
              <li key={share.id} className="grid">
                <ShareCard locale={locale} share={share} />
              </li>
            ))}
          </ul>
          {nextCursor && (
            <div className="flex justify-center">
              <button
                type="button"
                onClick={() => void loadMore()}
                disabled={loadingMore}
                className="inline-flex min-h-11 items-center gap-2 rounded-full border border-border bg-card px-5 text-sm font-semibold transition-colors hover:border-primary/50 hover:text-primary disabled:opacity-60"
              >
                {loadingMore ? (
                  <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
                ) : null}
                {loadingMore ? t.loadingMore : t.loadMore}
              </button>
            </div>
          )}
        </>
      ) : !error ? (
        <EmptyState
          locale={locale}
          filtered={filtered || query.q !== ""}
          onClear={() => setQuery({ q: "", kind: "", sort: "new" })}
        />
      ) : null}
    </div>
  );
}
