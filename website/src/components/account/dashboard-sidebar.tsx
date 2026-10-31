"use client";

import Link from "next/link";
import { ArrowLeft, BadgeCheck, Bell, LayoutDashboard, PackageOpen, ShieldCheck, UserRound } from "lucide-react";

import { InitialTile } from "@/components/community/tile";
import { LocaleSwitch } from "@/components/locale-switch";
import { ThemeToggle } from "@/components/theme-toggle";
import { Badge } from "@/components/ui/badge";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import type { Locale } from "@/i18n/config";
import { getMessages, type Messages } from "@/i18n/messages";
import { useUnreadCount } from "@/lib/queries";

import { DASHBOARD_TABS, dashboardTabHref, showsOfficialBadge, type DashboardIdentity, type DashboardTab } from "./dashboard-utils";

const TAB_LABELS: Record<DashboardTab, keyof Messages["dashboard"]> = {
  overview: "tabOverview",
  shares: "tabShares",
  profile: "tabProfile",
  security: "tabSecurity",
  notifications: "tabNotifications",
};

const TAB_ICONS = {
  overview: LayoutDashboard,
  shares: PackageOpen,
  profile: UserRound,
  security: ShieldCheck,
  notifications: Bell,
} as const;

/**
 * 个人控制台的左侧导航。
 *
 * 与管理台共用同一套 shadcn sidebar：桌面粘在左边，窄屏变成抽屉。分区仍然是真正的链接
 * (`?tab=`)，普通点击由父组件就地切换、不重新请求整页；中键 / 复制地址仍然成立。
 *
 * 底部只放**公开身份**：昵称、短名、官方徽标。邮箱只属于「个人信息」，不能在这里再出现一次。
 */
export function DashboardSidebar({
  locale,
  active,
  copy,
  identity,
  shareCount,
  onSelect,
}: {
  locale: Locale;
  active: DashboardTab;
  copy: Messages["dashboard"];
  identity: DashboardIdentity & { avatar_seed?: string | null };
  shareCount: number;
  onSelect: (tab: DashboardTab) => void;
}) {
  const { setOpen } = useSidebar();
  const unread = useUnreadCount().data ?? 0;
  const name = identity.display_name?.trim() || identity.handle?.trim() || copy.title;
  const handle = identity.handle?.trim() ?? "";
  const seed = identity.avatar_seed?.trim() || handle || name;
  const officialLabel = getMessages(locale).community.official;
  const backToCommunity = getMessages(locale).community.backToCommunity;
  const showOfficial = showsOfficialBadge(identity) && !name.includes(officialLabel);
  const otherLocale = locale === "zh" ? "en" : "zh";

  return (
    <Sidebar>
      <SidebarHeader>
        <Link href={`/${locale}`} className="flex items-center gap-2.5 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
          <span className="grid size-9 place-items-center rounded-lg bg-foreground font-display text-sm font-bold text-background">M</span>
          <span className="grid min-w-0 gap-0.5">
            <strong className="truncate text-sm font-semibold">MosaelCloud</strong>
            <span className="truncate text-[11px] text-muted-foreground">{copy.title}</span>
          </span>
        </Link>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>{copy.tabsLabel}</SidebarGroupLabel>
          <SidebarMenu>
            {DASHBOARD_TABS.map((tab) => {
              const Icon = TAB_ICONS[tab];
              const count = tab === "shares" ? shareCount : tab === "notifications" ? unread : 0;
              return (
                <SidebarMenuItem key={tab}>
                  <SidebarMenuButton
                    asChild
                    isActive={active === tab}
                    onClick={() => setOpen(false)}
                  >
                    <Link
                      href={dashboardTabHref(locale, tab)}
                      aria-current={active === tab ? "page" : undefined}
                      onClick={(event) => {
                        if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
                        event.preventDefault();
                        onSelect(tab);
                      }}
                    >
                      <Icon className="size-4" aria-hidden />
                      <span className="min-w-0 flex-1 truncate">{copy[TAB_LABELS[tab]]}</span>
                      {count > 0 && (
                        <Badge variant="secondary" className="h-5 min-w-5 justify-center px-1.5 font-mono text-[10px] tabular-nums">
                          {count > 99 ? "99+" : count}
                        </Badge>
                      )}
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              );
            })}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <div className="flex items-center gap-2.5">
          <InitialTile seed={seed} name={name} size="sm" />
          <div className="grid min-w-0 flex-1 gap-0.5">
            <strong className="truncate text-xs font-semibold">{name}</strong>
            {handle && <span className="truncate font-mono text-[11px] text-muted-foreground">@{handle}</span>}
          </div>
          {showOfficial && (
            <Badge variant="secondary">
              <BadgeCheck aria-hidden />
              {officialLabel}
            </Badge>
          )}
        </div>
        <div className="mt-3 grid gap-1 border-t border-border pt-3">
          <SidebarMenuButton asChild className="w-full justify-between">
            <Link href={`/${locale}/community`}>
              <span className="truncate">{backToCommunity}</span>
              <ArrowLeft className="size-4" aria-hidden />
            </Link>
          </SidebarMenuButton>
          <div className="flex items-center justify-between px-1">
            <LocaleSwitch locale={locale} label={copy.language} href={dashboardTabHref(otherLocale, active)} />
            <ThemeToggle label={copy.theme} />
          </div>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
