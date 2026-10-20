import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import { PageGlow } from "@/components/page-hero";
import { type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { cn } from "@/lib/utils";

import { communityTabs, type CommunityCounts, type CommunitySection } from "./community-tabs";

/**
 * 社区各页(首页 / 插件 / 工作流)共用的页头。
 *
 * 不再是官网内页那种占半屏的大标题:社区页是**拿来逛和找**的,进来第一眼该看到的是
 * 有哪些东西,而不是一句口号。所以页头压到一行标题 + 一句话,分区之间用 tab 切换 ——
 * 它们是同一个社区的两件事 + 它们的首页,不是三篇文章。
 *
 * **tab 只有一套,每个页面都渲染同一套。** 旧实现按 `active` 决定要不要放「分享」:
 * 切到 `/plugins` 或 `/workflows` 时这一项直接消失,用户看到的就是「分享列表没了」。
 * 现在 tab 全部来自 `communityTabs(locale, counts)`(它不收 active),`active` 只负责
 * 当前项的高亮 —— 当前页不可能改变「有哪些入口」。
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
  /**
   * 当前分区,**只用于高亮**,不参与生成 tab。不传 = 这一页不在 tab 里
   * (例如 `/community` 社区首页 —— 它仍可访问,但不占导航)。
   */
  active?: CommunitySection;
  counts: CommunityCounts;
  title: string;
  lede: string;
  /** 页头右上的行动按钮;`null` = 这一屏不给 CTA(由空态给出唯一的那个)。 */
  contribute?: { label: string; href: string } | null;
}) {
  const t = getMessages(locale);
  const tabs = communityTabs(locale, counts);
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
          {contribute && (
            <a
              href={contribute.href}
              // 站内的指南就地打开,仓库链接开新页。
              {...(/^https?:/.test(contribute.href) ? { target: "_blank", rel: "noreferrer" } : {})}
              className="inline-flex min-h-10 items-center gap-1.5 rounded-full border border-border bg-card px-4 text-sm font-semibold transition-colors hover:border-primary/50 hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              {contribute.label}
              <ArrowUpRight className="size-4" aria-hidden />
            </a>
          )}
        </div>
        <nav aria-label={t.community.name} className="mt-8 flex flex-wrap gap-x-6 gap-y-2">
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
              {tab.count !== undefined && (
                <span className="rounded-full bg-secondary px-2 py-0.5 font-mono text-[0.6875rem] tabular-nums text-muted-foreground">
                  {tab.count}
                </span>
              )}
            </Link>
          ))}
        </nav>
      </div>
    </section>
  );
}
