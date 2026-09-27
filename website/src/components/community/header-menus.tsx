"use client";

/**
 * 站头上社区相关的两样:「社区」下拉(工作流 / 插件 / 画板 / 统计),和右侧的账号区
 * (没登录是「登录 / 注册」,登录了是头像 + 菜单)。
 *
 * 「社区」只占一格:四个分区平铺进导航会把站头挤满,窄屏更放不下。
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { DropdownMenu } from "radix-ui";
import { BarChart3, ChevronDown, FileStack, LayoutGrid, LogOut, MonitorSmartphone, Puzzle, Share2, Shield, UserRound, Workflow } from "lucide-react";
import * as React from "react";

import { isNavLinkActive } from "@/components/nav-link";
import { isModerator, useSession } from "@/components/community/session-provider";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { communityLinks, communityMatch } from "@/lib/community/nav";
import type { PublicUser } from "@/lib/community/types";
import { cn } from "@/lib/utils";

const SECTION_ICONS = { workflows: Workflow, plugins: Puzzle, assets: UserRound, boards: LayoutGrid, stats: BarChart3 } as const;

const MENU =
  "z-[70] min-w-52 overflow-hidden rounded-2xl border border-border bg-popover p-1.5 text-popover-foreground shadow-xl data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95";
const ITEM =
  "flex cursor-pointer items-center gap-2.5 rounded-xl px-3 py-2 text-sm outline-none select-none data-[highlighted]:bg-secondary data-[highlighted]:text-foreground";

export function CommunityNav({ locale }: { locale: Locale }) {
  const t = getMessages(locale).nav;
  const pathname = usePathname();
  const active = isNavLinkActive(pathname, communityMatch(locale));
  return (
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger
        className={cn(
          "relative inline-flex items-center gap-1 rounded-full px-3.5 py-2 whitespace-nowrap outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/40",
          active ? "bg-brand-soft text-primary" : "text-muted-foreground hover:bg-secondary/75 hover:text-foreground data-[state=open]:bg-secondary/75",
        )}
      >
        {t.community}
        <ChevronDown className="size-3.5 opacity-70" aria-hidden />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="start" sideOffset={10} className={MENU}>
          {communityLinks(locale).map((section) => {
            const Icon = SECTION_ICONS[section.id];
            return (
              <DropdownMenu.Item key={section.href} asChild>
                <Link href={section.href} className={cn(ITEM, pathname.startsWith(section.href) && "text-primary")}>
                  <Icon className="size-4 text-muted-foreground" aria-hidden />
                  {section.label}
                </Link>
              </DropdownMenu.Item>
            );
          })}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

/** 头像:有图用图,没有用名字首字 —— 和社区卡片的图标块同一个办法。 */
export function Avatar({ user, size = "sm" }: { user: Pick<PublicUser, "handle" | "display_name" | "avatar_url">; size?: "sm" | "lg" }) {
  const initial = Array.from((user.display_name || user.handle).trim())[0]?.toUpperCase() ?? "?";
  const box = size === "lg" ? "size-20 text-3xl" : "size-8 text-sm";
  if (user.avatar_url) {
    // 头像来自社区服务的对象存储,尺寸不定,不走 next/image 的优化管线。
    // oxlint-disable-next-line nextjs/no-img-element
    return <img src={user.avatar_url} alt="" className={cn("shrink-0 rounded-full object-cover", box)} />;
  }
  return (
    <span aria-hidden className={cn("grid shrink-0 place-items-center rounded-full bg-brand-soft font-display font-bold text-primary", box)}>
      {initial}
    </span>
  );
}

export function accountLinks(locale: Locale, handle: string) {
  const t = getMessages(locale).nav;
  return [
    { href: localePath(locale, `/u/${handle}`), label: t.myProfile, icon: UserRound },
    { href: localePath(locale, "/account#submissions"), label: t.mySubmissions, icon: FileStack },
    { href: localePath(locale, "/account#shares"), label: t.myShares, icon: Share2 },
    { href: localePath(locale, "/account#sessions"), label: t.sessions, icon: MonitorSmartphone },
  ];
}

/**
 * 站头右侧的账号区。状态未知(水合那一帧、正在恢复会话)时占一个同宽的空位,不闪一下
 * 「登录」再变成头像。
 */
export function AccountMenu({ locale }: { locale: Locale }) {
  const t = getMessages(locale).nav;
  const { status, user, logout } = useSession();
  const pathname = usePathname();

  if (status === "unknown" || status === "loading") return <span aria-hidden className="hidden size-9 lg:inline-block" />;

  if (!user) {
    const next = pathname && !/\/(login|register|reset-password)$/.test(pathname) ? `?next=${encodeURIComponent(pathname)}` : "";
    return (
      <span className="hidden items-center gap-1 lg:inline-flex">
        <Link
          href={`${localePath(locale, "/login")}${next}`}
          className="inline-flex min-h-9 items-center rounded-full px-3.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
        >
          {t.login}
        </Link>
        {/* 1024–1280 之间站头放不下两颗:只留「登录」,登录页上有去注册的链接。 */}
        <Link
          href={`${localePath(locale, "/register")}${next}`}
          className="hidden min-h-9 items-center rounded-full border border-border px-3.5 text-sm font-medium transition-colors hover:border-foreground/30 xl:inline-flex"
        >
          {t.register}
        </Link>
      </span>
    );
  }

  return (
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger
        aria-label={t.accountMenu}
        className="hidden size-9 items-center justify-center rounded-full outline-none focus-visible:ring-3 focus-visible:ring-ring/40 lg:inline-flex"
      >
        <Avatar user={user} />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={10} className={MENU}>
          <div className="grid gap-0.5 px-3 pt-2 pb-2.5">
            <span className="truncate text-sm font-semibold">{user.display_name || user.handle}</span>
            <span className="truncate font-mono text-xs text-muted-foreground">@{user.handle}</span>
          </div>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          {accountLinks(locale, user.handle).map((link) => (
            <DropdownMenu.Item key={link.href} asChild>
              <Link href={link.href} className={ITEM}>
                <link.icon className="size-4 text-muted-foreground" aria-hidden />
                {link.label}
              </Link>
            </DropdownMenu.Item>
          ))}
          {isModerator(user) && (
            <DropdownMenu.Item asChild>
              <Link href={localePath(locale, "/admin")} className={ITEM}>
                <Shield className="size-4 text-muted-foreground" aria-hidden />
                {t.admin}
              </Link>
            </DropdownMenu.Item>
          )}
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item className={ITEM} onSelect={() => void logout()}>
            <LogOut className="size-4 text-muted-foreground" aria-hidden />
            {t.logout}
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

/** 窄屏菜单里的账号那一段:和桌面的下拉同一组入口,平铺成列表。 */
export function MobileAccountLinks({ locale, itemClass }: { locale: Locale; itemClass: string }) {
  const t = getMessages(locale).nav;
  const { user, logout } = useSession();
  if (!user) {
    return (
      <div className="grid grid-cols-2 gap-2 pt-4">
        <Link href={localePath(locale, "/login")} className="rounded-full border border-border px-4 py-3 text-center font-semibold">
          {t.login}
        </Link>
        <Link href={localePath(locale, "/register")} className="rounded-full border border-border px-4 py-3 text-center font-semibold">
          {t.register}
        </Link>
      </div>
    );
  }
  return (
    <>
      <div className="flex items-center gap-3 px-1 pt-4 pb-2">
        <Avatar user={user} />
        <span className="min-w-0 truncate font-semibold">@{user.handle}</span>
      </div>
      {accountLinks(locale, user.handle).map((link) => (
        <Link key={link.href} href={link.href} className={itemClass}>
          {link.label}
        </Link>
      ))}
      {isModerator(user) && (
        <Link href={localePath(locale, "/admin")} className={itemClass}>
          {t.admin}
        </Link>
      )}
      <button type="button" onClick={() => void logout()} className={cn(itemClass, "text-left")}>
        {t.logout}
      </button>
    </>
  );
}
