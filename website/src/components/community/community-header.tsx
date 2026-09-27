import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import { PageGlow } from "@/components/page-hero";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { cn } from "@/lib/utils";

/**
 * 社区两页(插件 / 工作流)共用的页头。
 *
 * 不再是官网内页那种占半屏的大标题:社区页是**拿来逛和找**的,进来第一眼该看到的是
 * 有哪些东西,而不是一句口号。所以页头压到一行标题 + 一句话,两页之间用标签页切换 ——
 * 它们是同一个社区的两个分区,不是两篇文章。
 */
export function CommunityHeader({
  locale,
  active,
  counts,
  title,
  lede,
  contribute,
}: {
  locale: Locale;
  active: "plugins" | "workflows";
  counts: { plugins: number; workflows: number };
  title: string;
  lede: string;
  contribute: { label: string; href: string };
}) {
  const t = getMessages(locale);
  const tabs = [
    { id: "plugins" as const, label: t.plugins.title, count: counts.plugins, href: localePath(locale, "/plugins") },
    { id: "workflows" as const, label: t.workflows.title, count: counts.workflows, href: localePath(locale, "/workflows") },
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
          <a
            href={contribute.href}
            // 站内的指南就地打开,仓库链接开新页。
            {...(/^https?:/.test(contribute.href) ? { target: "_blank", rel: "noreferrer" } : {})}
            className="inline-flex min-h-10 items-center gap-1.5 rounded-full border border-border bg-card px-4 text-sm font-semibold transition-colors hover:border-primary/50 hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            {contribute.label}
            <ArrowUpRight className="size-4" aria-hidden />
          </a>
        </div>
        <nav aria-label={t.community.name} className="mt-8 flex gap-6">
          {tabs.map((tab) => (
            <Link
              key={tab.id}
              href={tab.href}
              aria-current={tab.id === active ? "page" : undefined}
              className={cn(
                "-mb-px inline-flex items-center gap-2 border-b-2 pb-3 text-sm font-semibold transition-colors",
                tab.id === active
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
              <span className="rounded-full bg-secondary px-2 py-0.5 font-mono text-[0.6875rem] tabular-nums text-muted-foreground">
                {tab.count}
              </span>
            </Link>
          ))}
        </nav>
      </div>
    </section>
  );
}
