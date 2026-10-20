"use client";

import Link from "next/link";
import type { MouseEvent } from "react";

import { PageGlow } from "@/components/page-hero";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { cn } from "@/lib/utils";

import { DASHBOARD_TABS, dashboardTabHref, type DashboardTab } from "./dashboard-utils";

/**
 * 「我的」控制台的页头。
 *
 * 形态借自社区页头(`components/community/community-header.tsx`):一行标题 + 一句话,
 * 下面是一条贴底边的 tab 栏 —— 五个分区是同一个控制台的不同切面,不是五篇文章。区别只在
 * 这里是**私有页面**:tab 的地址是 `?tab=`,不做搜索、不显示任何计数。
 *
 * tab 是真正的链接(`href` + `aria-current`):中键新标签、复制地址、刷新,都还能回到同一个
 * 分区;普通点按时由父组件就地换分区并 `replaceState` 改地址,不走服务端往返。
 */
const TAB_LABELS: Record<DashboardTab, keyof Messages["dashboard"]> = {
  overview: "tabOverview",
  shares: "tabShares",
  profile: "tabProfile",
  devices: "tabDevices",
  notifications: "tabNotifications",
};

export function DashboardHeader({
  locale,
  active,
  copy,
  onSelect,
}: {
  locale: Locale;
  active: DashboardTab;
  copy: Messages["dashboard"];
  onSelect: (tab: DashboardTab) => void;
}) {
  const select = (event: MouseEvent<HTMLAnchorElement>, tab: DashboardTab) => {
    // 只拦普通左键:中键 / Ctrl(⌘)+ 点击、右键新标签都保留浏览器自己的行为。
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    onSelect(tab);
  };

  return (
    <section className="relative isolate -mt-20 overflow-hidden border-b border-border bg-paper">
      <PageGlow />
      <div className="mx-auto max-w-[76rem] px-5 pt-32 sm:px-8 sm:pt-36">
        <p className="m-0 font-mono text-xs font-bold tracking-widest text-primary uppercase">{copy.eyebrow}</p>
        <div className="mt-3 min-w-0 max-w-2xl">
          <h1 className="m-0 font-display text-4xl font-bold tracking-[-0.035em] text-balance sm:text-5xl">{copy.title}</h1>
          <p className="mt-3 mb-0 text-base leading-7 text-muted-foreground">{copy.lede}</p>
        </div>
        <nav aria-label={copy.tabsLabel} className="mt-8 flex flex-wrap gap-x-6 gap-y-1">
          {DASHBOARD_TABS.map((tab) => (
            <Link
              key={tab}
              href={dashboardTabHref(locale, tab)}
              aria-current={tab === active ? "page" : undefined}
              onClick={(event) => select(event, tab)}
              className={cn(
                "-mb-px inline-flex items-center border-b-2 pb-3 text-sm font-semibold transition-colors",
                tab === active
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {copy[TAB_LABELS[tab]]}
            </Link>
          ))}
        </nav>
      </div>
    </section>
  );
}
