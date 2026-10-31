"use client";

import Link from "next/link";
import { ExternalLink, Menu } from "lucide-react";

import { Button } from "@/components/ui/button";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { type Locale, localePath } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";

import type { DashboardIdentity, DashboardTab } from "./dashboard-utils";

const TAB_LABELS: Record<DashboardTab, keyof Messages["dashboard"]> = {
  overview: "tabOverview",
  shares: "tabShares",
  profile: "tabProfile",
  security: "tabSecurity",
  notifications: "tabNotifications",
};

const TAB_LEDES: Record<DashboardTab, keyof Messages["dashboard"]> = {
  overview: "overviewLede",
  shares: "sharesLede",
  profile: "profileLede",
  security: "securityLede",
  notifications: "notificationsLede",
};

/**
 * 控制台内容区的页头。
 *
 * 只负责「当前在哪一屏」和去公开主页的动作，不再画营销页那种大标题 + tab 条：分区导航在左侧，
 * 昵称 / 短名 / 官方徽标只在侧栏底部出现一次，这里不重复。窄屏的侧栏开关也在这里，保证抽屉
 * 入口永远在内容区左上角。
 */
export function DashboardHeader({
  locale,
  active,
  copy,
  identity,
}: {
  locale: Locale;
  active: DashboardTab;
  copy: Messages["dashboard"];
  identity: DashboardIdentity | null;
}) {
  const handle = identity?.handle?.trim() ?? "";

  return (
    <header className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-5">
      <div className="flex min-w-0 items-start gap-3">
        <SidebarTrigger aria-label={copy.tabsLabel} className="mt-0.5 shrink-0">
          <Menu className="size-4" />
        </SidebarTrigger>
        <div className="min-w-0">
          <p className="m-0 font-mono text-[11px] font-semibold tracking-[0.16em] text-muted-foreground uppercase">
            {copy.eyebrow} / {copy.title}
          </p>
          <h1 className="mt-1.5 mb-0 font-display text-2xl font-semibold tracking-[-0.03em] text-balance sm:text-3xl">
            {copy[TAB_LABELS[active]]}
          </h1>
          <p className="mt-1.5 mb-0 max-w-2xl text-sm leading-6 text-muted-foreground">{copy[TAB_LEDES[active]]}</p>
        </div>
      </div>

      {handle && (
        <Button asChild variant="outline" size="sm" className="sm:ml-auto">
          <Link href={localePath(locale, `/users/${handle}`)}>
            {copy.viewPublicProfile}
            <ExternalLink className="size-3.5" aria-hidden />
          </Link>
        </Button>
      )}
    </header>
  );
}
