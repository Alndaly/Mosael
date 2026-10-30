"use client";

import Link from "next/link";
import { BadgeCheck } from "lucide-react";
import type { MouseEvent } from "react";

import { PageGlow } from "@/components/page-hero";
import type { Locale } from "@/i18n/config";
import { getMessages, type Messages } from "@/i18n/messages";
import { cn } from "@/lib/utils";

import {
  DASHBOARD_TABS,
  dashboardTabHref,
  showsOfficialBadge,
  type DashboardIdentity,
  type DashboardTab,
} from "./dashboard-utils";

/**
 * 「我的」控制台的页头。
 *
 * 形态借自社区页头(`components/community/community-header.tsx`):一行标题 + 一句话,
 * 下面是一条贴底边的 tab 栏 —— 四个分区是同一个控制台的不同切面,不是四篇文章。区别只在
 * 这里是**私有页面**:tab 的地址是 `?tab=`,不做搜索、不显示任何计数。
 *
 * tab 是真正的链接(`href` + `aria-current`):中键新标签、复制地址、刷新,都还能回到同一个
 * 分区;普通点按时由父组件就地换分区并 `replaceState` 改地址,不走服务端往返。
 *
 * 标题下面那行是**当前账号的公开身份**(昵称 + 短名):「这是我的账号」最该在这一页说清。
 * 官方账号在名字后面跟一枚「官方」徽标 —— 与分享卡片上的那枚同一个视觉语言
 * (`components/community/shares.tsx`:BadgeCheck + `community.official`),不另造样式。
 */
const TAB_LABELS: Record<DashboardTab, keyof Messages["dashboard"]> = {
  overview: "tabOverview",
  shares: "tabShares",
  profile: "tabProfile",
  security: "tabSecurity",
  notifications: "tabNotifications",
};

export function DashboardHeader({
  locale,
  active,
  copy,
  identity,
  onSelect,
}: {
  locale: Locale;
  active: DashboardTab;
  copy: Messages["dashboard"];
  identity: DashboardIdentity | null;
  onSelect: (tab: DashboardTab) => void;
}) {
  const select = (event: MouseEvent<HTMLAnchorElement>, tab: DashboardTab) => {
    // 只拦普通左键:中键 / Ctrl(⌘)+ 点击、右键新标签都保留浏览器自己的行为。
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    onSelect(tab);
  };

  const name = identity?.display_name?.trim() || identity?.handle?.trim() || "";
  const handle = identity?.handle?.trim() ?? "";
  // 和分享卡片同一个词,不复制一份「官方」到控制台文案里。
  const officialLabel = getMessages(locale).community.official;

  return (
    <section className="relative isolate -mt-20 overflow-hidden border-b border-border bg-paper">
      <PageGlow />
      <div className="mx-auto max-w-[76rem] px-5 pt-32 sm:px-8 sm:pt-36">
        <p className="m-0 font-mono text-xs font-bold tracking-widest text-primary uppercase">{copy.eyebrow}</p>
        <div className="mt-3 min-w-0 max-w-2xl">
          <h1 className="m-0 font-display text-4xl font-bold tracking-[-0.035em] text-balance sm:text-5xl">{copy.title}</h1>
          <p className="mt-3 mb-0 text-base leading-7 text-muted-foreground">{copy.lede}</p>
          {name && (
            <p className="mt-4 mb-0 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm text-muted-foreground">
              <span className="font-semibold text-foreground">{name}</span>
              {handle && <span className="font-mono text-xs">@{handle}</span>}
              {/*
                徽标是**文字**(官方 / Official),不是纯图标;图标对读屏隐藏。
                它排在名字之后、与名字同在一行,读屏按自然顺序念成「<名字> 官方」,
                所以不需要额外用一个 aria-label 去替名字造句(那会把可见文字读两遍的风险换成
                一个非交互元素上的标签,支持面反而更窄)。
              */}
              {showsOfficialBadge(identity) && (
                <span className="inline-flex shrink-0 items-center gap-0.5 text-xs font-medium text-primary">
                  <BadgeCheck className="size-3.5" aria-hidden />
                  {officialLabel}
                </span>
              )}
            </p>
          )}
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

