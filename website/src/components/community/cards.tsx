import Link from "next/link";
import { BadgeCheck, Code2, Download, Heart, LayoutGrid, Plug, Shield, SquareTerminal, Users, Wrench } from "lucide-react";
import type * as React from "react";

import { PluginTile, WorkflowTile } from "@/components/community/tile";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { formatCount, formatDate } from "@/lib/community/format";
import { toPlainText } from "@/lib/inline-markdown";
import type { PluginSummary, PublicUser, ShareSummary, WorkflowSummary } from "@/lib/community/types";
import { cn } from "@/lib/utils";

/**
 * 社区卡片与署名行。**没有 hook、不是客户端组件**:列表页(客户端,要加载更多)和详情页的
 * 「更多」、作者主页(服务端)用的是同一张卡。
 */

/** 版本号那一格:还没有公开的版本(插件在审核中)时是一道横线。 */
export function versionLabel(version: string | null | undefined): string {
  return version ? `v${version}` : "—";
}

/**
 * 署名那一行:作者 + 官方 / 社区标记 + 版本。官方条目迁到 `official` 作者名下(ADR 0026 §4),
 * 服务在条目上给出 `official`。`link` 时作者名链到主页(卡片本身是链接时不能再套)。
 */
export function Byline({
  locale,
  author,
  official,
  version,
  link = false,
}: {
  locale: Locale;
  author: PublicUser;
  official: boolean;
  version: string;
  link?: boolean;
}) {
  const t = getMessages(locale).community;
  const name = author.display_name || author.handle;
  return (
    <span className="inline-flex min-w-0 flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
      {link && !official ? (
        <Link href={localePath(locale, `/u/${author.handle}`)} className="truncate hover:text-foreground hover:underline">
          {name}
        </Link>
      ) : (
        <span className="truncate">{name}</span>
      )}
      {official ? (
        <span className="inline-flex items-center gap-0.5 font-medium text-primary">
          <BadgeCheck className="size-3.5" aria-hidden />
          {t.official}
        </span>
      ) : (
        <span className="inline-flex items-center gap-0.5 font-medium">
          <Users className="size-3.5" aria-hidden />
          {t.communityBadge}
        </span>
      )}
      <span aria-hidden>·</span>
      <span className="font-mono tabular-nums">{version}</span>
    </span>
  );
}

export function Meta({ icon: Icon, children, tone }: { icon: typeof Shield; children: React.ReactNode; tone?: "warn" }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", tone === "warn" && "font-medium text-[color:var(--tile-4)]")}>
      <Icon className="size-3.5 shrink-0" aria-hidden />
      {children}
    </span>
  );
}

export const CARD =
  "group flex min-w-0 flex-col rounded-2xl border border-border bg-card p-5 transition-[border-color,transform,box-shadow] hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-[0_10px_30px_-18px_color-mix(in_oklab,var(--primary)_60%,transparent)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring motion-reduce:transition-none motion-reduce:hover:translate-y-0";

export const GRID = "m-0 grid list-none grid-cols-[minmax(0,1fr)] gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3";

function Tags({ tags }: { tags: string[] }) {
  if (tags.length === 0) return null;
  return (
    <span className="mt-3 flex flex-wrap gap-1.5">
      {tags.slice(0, 4).map((tag) => (
        <span key={tag} className="rounded-full bg-secondary px-2 py-0.5 text-[0.6875rem] text-muted-foreground">
          #{tag}
        </span>
      ))}
    </span>
  );
}

function Counts({ locale, downloads, likes }: { locale: Locale; downloads: number; likes: number }) {
  const t = getMessages(locale).community;
  return (
    <>
      <Meta icon={Download}>
        <span className="tabular-nums">{formatCount(downloads, locale)}</span>
        <span className="sr-only">{t.downloads}</span>
      </Meta>
      <Meta icon={Heart}>
        <span className="tabular-nums">{formatCount(likes, locale)}</span>
        <span className="sr-only">{t.likes}</span>
      </Meta>
    </>
  );
}

export function PluginCard({ locale, item }: { locale: Locale; item: PluginSummary }) {
  const t = getMessages(locale).plugins;
  return (
    <Link href={localePath(locale, `/plugins/${item.slug}`)} className={CARD}>
      <div className="flex min-w-0 items-center gap-3.5">
        <PluginTile seed={item.plugin_id || item.slug} name={item.title} cover={item.cover_url} />
        <div className="grid min-w-0 gap-0.5">
          <h3 className="m-0 truncate text-base font-semibold tracking-tight group-hover:text-primary">{item.title}</h3>
          <Byline locale={locale} author={item.author} official={item.official} version={versionLabel(item.version)} />
        </div>
      </div>
      {/* 卡片整张是链接、简介只截三行:这里用纯文本,格式留给详情页。 */}
      <p className="mt-4 mb-0 line-clamp-3 flex-1 text-sm leading-6 text-muted-foreground">{toPlainText(item.summary)}</p>
      <Tags tags={item.tags} />
      <div className="mt-5 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-border pt-4 text-xs text-muted-foreground">
        <Meta icon={item.runtime === "mcp" ? Plug : SquareTerminal}>{item.runtime === "mcp" ? t.kindMcp : t.kindScript}</Meta>
        <Meta icon={Shield}>{item.permissions.length > 0 ? `${item.permissions.length} ${t.permissions}` : t.noPermissions}</Meta>
        <Counts locale={locale} downloads={item.downloads} likes={item.likes} />
      </div>
    </Link>
  );
}

export function WorkflowCard({ locale, item }: { locale: Locale; item: WorkflowSummary }) {
  const t = getMessages(locale).workflows;
  return (
    <Link href={localePath(locale, `/workflows/${item.slug}`)} className={CARD}>
      <div className="flex min-w-0 items-center gap-3.5">
        <WorkflowTile slug={item.slug} cover={item.cover_url} />
        <div className="grid min-w-0 gap-0.5">
          <h3 className="m-0 truncate text-base font-semibold tracking-tight group-hover:text-primary">{item.title}</h3>
          <Byline locale={locale} author={item.author} official={item.official} version={versionLabel(item.version)} />
        </div>
      </div>
      <p className="mt-4 mb-0 line-clamp-3 flex-1 text-sm leading-6 text-muted-foreground">{toPlainText(item.summary)}</p>
      <Tags tags={item.tags} />
      <div className="mt-5 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-border pt-4 text-xs text-muted-foreground">
        <Meta icon={Wrench}>{`${item.node_count} ${t.nodes}`}</Meta>
        {item.has_code && (
          <Meta icon={Code2} tone="warn">
            {t.codeNode}
          </Meta>
        )}
        <Counts locale={locale} downloads={item.downloads} likes={item.likes} />
      </div>
    </Link>
  );
}

/**
 * 进分享查看页用普通的 `<a>`,不用 next/link:客户端导航不会重新拿文档,那一页的严格 CSP(proxy.ts)
 * 就落不到浏览器上。整页加载才带着它。
 */
export function BoardCard({ locale, share }: { locale: Locale; share: ShareSummary }) {
  const t = getMessages(locale);
  return (
    <a href={localePath(locale, `/b/${share.slug}`)} className={cn(CARD, "p-0")}>
      <div className="grid aspect-[16/10] place-items-center overflow-hidden rounded-t-2xl border-b border-border bg-secondary/50">
        {share.cover_url ? (
          // oxlint-disable-next-line nextjs/no-img-element
          <img src={share.cover_url} alt="" loading="lazy" className="size-full object-cover" />
        ) : (
          <LayoutGrid className="size-8 text-muted-foreground" aria-hidden />
        )}
      </div>
      <div className="grid gap-1 p-4">
        <h3 className="m-0 truncate text-base font-semibold tracking-tight group-hover:text-primary">{share.title || t.boards.untitled}</h3>
        <span className="flex flex-wrap gap-x-2 text-xs text-muted-foreground">
          {share.owner && <span className="truncate">{share.owner.display_name || share.owner.handle}</span>}
          <span>{formatDate(share.updated_at, locale)}</span>
        </span>
      </div>
    </a>
  );
}
