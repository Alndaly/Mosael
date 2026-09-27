import Link from "next/link";
import type * as React from "react";

import { PageGlow } from "@/components/page-hero";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { cn } from "@/lib/utils";

export type CommunitySection = "workflows" | "plugins" | "assets" | "boards" | "stats";

/**
 * 社区几个分区(工作流 / 插件 / 资产 / 画板 / 统计)共用的页头。
 *
 * 不再是官网内页那种占半屏的大标题:社区页是**拿来逛和找**的,进来第一眼该看到的是
 * 有哪些东西,而不是一句口号。所以页头压到一行标题 + 一句话,分区之间用标签页切换 ——
 * 它们是同一个社区的几个分区,不是几篇文章。
 */
export function CommunityHeader({
  locale,
  active,
  title,
  lede,
  actions,
}: {
  locale: Locale;
  active: CommunitySection;
  title: string;
  lede: string;
  actions?: React.ReactNode;
}) {
  const t = getMessages(locale);
  const tabs = [
    { id: "workflows" as const, label: t.nav.workflows, href: localePath(locale, "/workflows") },
    { id: "plugins" as const, label: t.nav.plugins, href: localePath(locale, "/plugins") },
    { id: "assets" as const, label: t.nav.assets, href: localePath(locale, "/assets") },
    { id: "boards" as const, label: t.nav.boards, href: localePath(locale, "/boards") },
    { id: "stats" as const, label: t.nav.stats, href: localePath(locale, "/community/stats") },
  ];
  return (
    <section className="relative isolate -mt-20 overflow-hidden border-b border-border bg-paper">
      <PageGlow />
      <div className="mx-auto max-w-[76rem] px-5 pt-32 sm:px-8 sm:pt-36">
        <p className="m-0 font-mono text-xs font-bold tracking-widest text-primary uppercase">{t.community.name}</p>
        <div className="mt-3 flex flex-wrap items-end justify-between gap-x-10 gap-y-5">
          <div className="min-w-0 max-w-2xl">
            <h1 className="m-0 font-display text-4xl font-bold tracking-[-0.035em] text-balance sm:text-5xl">{title}</h1>
            <p className="mt-3 mb-0 text-base leading-7 text-muted-foreground">{lede}</p>
          </div>
          {actions && <div className="flex flex-wrap gap-2.5">{actions}</div>}
        </div>
        {/* 窄屏几个标签横向滚动,不折行。 */}
        <nav aria-label={t.community.name} className="-mx-5 mt-8 flex gap-6 overflow-x-auto px-5 sm:mx-0 sm:px-0">
          {tabs.map((tab) => (
            <Link
              key={tab.id}
              href={tab.href}
              aria-current={tab.id === active ? "page" : undefined}
              className={cn(
                "-mb-px inline-flex shrink-0 items-center gap-2 border-b-2 pb-3 text-sm font-semibold transition-colors",
                tab.id === active ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
            </Link>
          ))}
        </nav>
      </div>
    </section>
  );
}

/** 页头右上角的按钮:主操作(提交)实心,次操作(指南)描边。 */
export function HeaderAction({ href, primary = false, children }: { href: string; primary?: boolean; children: React.ReactNode }) {
  const external = /^https?:/.test(href);
  return (
    <Link
      href={href}
      {...(external ? { target: "_blank", rel: "noreferrer" } : {})}
      className={cn(
        "inline-flex min-h-10 items-center gap-1.5 rounded-full px-4 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        primary ? "bg-primary text-primary-foreground hover:bg-primary/88" : "border border-border bg-card hover:border-primary/50 hover:text-primary",
      )}
    >
      {children}
    </Link>
  );
}
