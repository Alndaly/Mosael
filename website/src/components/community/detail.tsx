import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type * as React from "react";

import { Byline } from "@/components/community/browse";
import { PageGlow } from "@/components/page-hero";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { InlineMarkdown } from "@/lib/inline-markdown";
import { cn } from "@/lib/utils";

/**
 * 社区详情页的骨架:面包屑 + 身份栏(图标、名字、署名、一句话、主操作),下面左正文右侧栏。
 *
 * 版式照应用商店 / 插件市场的习惯来:决定「装不装」要看的东西(谁写的、要什么权限、
 * 要准备什么)在右栏一眼看全,左栏是细读的内容。
 */
export function DetailHeader({
  locale,
  section,
  tile,
  name,
  author,
  version,
  official,
  builtIn = false,
  summary,
  actions,
}: {
  locale: Locale;
  section: { label: string; href: string };
  tile: React.ReactNode;
  name: string;
  author: string;
  version: string;
  official: boolean;
  /** 随应用内置的插件:署名旁标出来(见 Byline)。 */
  builtIn?: boolean;
  /** 数据里的简介,行内 markdown。 */
  summary: string;
  actions: React.ReactNode;
}) {
  const t = getMessages(locale).community;
  return (
    <section className="relative isolate -mt-20 overflow-hidden border-b border-border bg-paper">
      <PageGlow />
      <div className="mx-auto max-w-[76rem] px-5 pt-30 pb-10 sm:px-8 sm:pt-34">
        <nav aria-label="breadcrumb" className="flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
          <Link href={localePath(locale, "/plugins")} className="hover:text-foreground">
            {t.name}
          </Link>
          <ChevronRight className="size-3.5" aria-hidden />
          <Link href={localePath(locale, section.href)} className="hover:text-foreground">
            {section.label}
          </Link>
          <ChevronRight className="size-3.5" aria-hidden />
          <span aria-current="page" className="truncate text-foreground">
            {name}
          </span>
        </nav>
        {/* 窄屏上下堆叠:身份栏和按钮挤一行的话,名字和简介会被压成一列一个字。 */}
        <div className="mt-8 flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between lg:gap-10">
          <div className="flex min-w-0 flex-1 items-start gap-4 sm:gap-5">
            {tile}
            <div className="grid min-w-0 gap-2">
              <h1 className="m-0 font-display text-3xl font-bold tracking-[-0.03em] text-balance sm:text-4xl">{name}</h1>
              <Byline locale={locale} author={author} version={version} official={official} builtIn={builtIn} />
              <p className="m-0 max-w-[46rem] text-base leading-7 text-muted-foreground">
                <InlineMarkdown text={summary} />
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2.5 lg:shrink-0">{actions}</div>
        </div>
      </div>
    </section>
  );
}

/** 主操作 / 次操作两种按钮。站外链接(下载、源码)开新页,`mosael://` 就地唤起。 */
export function ActionLink({
  href,
  primary = false,
  download,
  children,
}: {
  href: string;
  primary?: boolean;
  download?: boolean;
  children: React.ReactNode;
}) {
  const external = /^https?:/.test(href);
  return (
    <a
      href={href}
      download={download || undefined}
      {...(external ? { target: "_blank", rel: "noreferrer" } : {})}
      className={cn(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-full px-5 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        primary
          ? "bg-primary text-primary-foreground hover:bg-primary/88"
          : "border border-border bg-card hover:border-foreground/30",
      )}
    >
      {children}
    </a>
  );
}

export function DetailBody({ main, aside }: { main: React.ReactNode; aside: React.ReactNode }) {
  return (
    <div className="bg-paper">
      {/* 单列时也要写明 minmax(0,1fr):隐式的列按内容最宽处撑开,README 里一段长代码就能把整列顶出屏幕。 */}
      <div className="mx-auto grid max-w-[76rem] grid-cols-[minmax(0,1fr)] gap-10 px-5 py-12 sm:px-8 lg:grid-cols-[minmax(0,1fr)_20rem] lg:gap-14">
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-12">{main}</div>
        <aside className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-4">{aside}</aside>
      </div>
    </div>
  );
}

export function Section({ id, title, count, children }: { id: string; title: string; count?: number; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-28">
      <h2 className="mt-0 mb-5 flex items-center gap-2 border-b border-border pb-3 text-lg font-semibold tracking-tight">
        {title}
        {count !== undefined && (
          <span className="rounded-full bg-secondary px-2 py-0.5 font-mono text-xs tabular-nums text-muted-foreground">{count}</span>
        )}
      </h2>
      {children}
    </section>
  );
}

/** 右栏的一张卡。 */
export function SideCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-border bg-card p-5">
      <h2 className="mt-0 mb-4 text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

/** 标签 / 值两列。 */
export function InfoList({ rows }: { rows: { label: string; value: React.ReactNode }[] }) {
  return (
    <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-3 text-sm">
      {rows.map((row) => (
        <div key={row.label} className="contents">
          <dt className="text-muted-foreground">{row.label}</dt>
          <dd className="m-0 min-w-0 text-right [overflow-wrap:anywhere]">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** 编号步骤。装插件、导入工作流都是三步,形状一样。 */
export function Steps({ steps }: { steps: readonly string[] }) {
  return (
    <ol className="m-0 grid list-none gap-3 p-0 text-sm">
      {steps.map((step, index) => (
        <li key={step} className="flex items-start gap-3">
          <span className="grid size-6 shrink-0 place-items-center rounded-full bg-brand-soft font-mono text-xs font-bold text-primary tabular-nums">
            {index + 1}
          </span>
          <span className="pt-0.5 leading-6">{step}</span>
        </li>
      ))}
    </ol>
  );
}
