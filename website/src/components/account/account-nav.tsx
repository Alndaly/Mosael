"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { LogOut } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { Locale } from "@/i18n/config";
import { cloudAccount, formatUnreadBadge, type CloudUser } from "@/lib/cloud";
import { invalidateAfterSignOut } from "@/lib/query-invalidation";
import { useUnreadCount, useViewer } from "@/lib/queries";

/**
 * 站头的账号入口。未登录时是「登录」次级按钮,登录后是**一颗圆形头像** —— 账号名的
 * 第一个字,点进去是**「我的」控制台**(概览 / 我的分享 / 个人信息 / 设备 / 通知)。
 *
 * 未登录那颗是 816c0c714 定稿的**次级按钮**:复用账号页那颗 `Button variant="outline"`,
 * 描边 + 次要文字色,与「下载」的实心主色隔开一级 —— 它在站头里紧贴「下载」左侧,是这一簇
 * 里唯一的次级按钮。已登录的入口不跟「下载」抢重量:头像是一块标识,不是按钮。
 *
 * 头像只有一个字,直径和旁边那排图标按钮同一档(`size-9`,36px —— GitHub、主题、语言、
 * 搜索都量过,都是这个尺寸)。底色不是随机的:和社区卡片那块 `InitialTile` 共用
 * `--tile-*` 那六个色相,由名字算一个 hash 取一个 —— 同一个人在列表、详情、站头永远是
 * 同一块颜色。
 *
 * 头像右下角是**未读通知角标**:`useUnreadCount()` 读 `unread-count`,0 条不显示,超过 99
 * 收成 `99+`(格式化在 `lib/cloud.ts` 的 `formatUnreadBadge` 里,和测试同一份)。
 * **P1 不轮询** —— 这里是站头,不是收件箱;从后台切回来时由查询默认的
 * `refetchOnWindowFocus` 刷一下。
 *
 * 身份与未读数都住在 TanStack Query 的缓存里(键见 `lib/queryKeys.ts`):登录 / 退出 /
 * 改昵称头像之后由 `lib/query-invalidation.ts` 点名失效,站头才会跟着换字、换色、换
 * `aria-label`。它只问云端 `/me` 与 `/notifications/unread-count` —— 不碰本地后端,
 * 也不把邮箱塞进站头那一行(窄屏放不下)。
 */

/** 顶栏只关心这三列:显示名 → 短名 → 邮箱前缀。 */
type AccountIdentity = Pick<CloudUser, "display_name" | "handle" | "email">;

/** 和 `components/community/tile.tsx` 共用的一组色相 token:六个亮度相近,谁都不特别跳。 */
const TILE_HUES = ["--tile-1", "--tile-2", "--tile-3", "--tile-4", "--tile-5", "--tile-6"] as const;

/** 账号名:昵称优先,其次短名,最后退到邮箱前缀 —— 完整邮箱不进站头,也不进 DOM。 */
function accountName(user: AccountIdentity): string {
  const display = user.display_name?.trim();
  if (display) return display;
  const handle = user.handle?.trim();
  if (handle) return handle;
  return user.email?.split("@")[0]?.trim() ?? "";
}

/** 第一个字:按字形取(中文取第一个字、emoji 不会被截成半个),英文再大写。 */
function initialOf(name: string): string {
  return Array.from(name.trim())[0]?.toUpperCase() ?? "?";
}

/** 名字 → 色相。纯函数:同一个名字永远同一支颜色,刷新、换机器都不变。 */
function hueOf(seed: string): string {
  let hash = 0;
  for (const char of seed) hash = (hash * 31 + (char.codePointAt(0) ?? 0)) >>> 0;
  return `var(${TILE_HUES[hash % TILE_HUES.length]})`;
}

/** 底色 = 色相 22% 混进卡片色;字母用正文字色,亮暗两档都还读得清。 */
function avatarStyle(seed: string): CSSProperties {
  return { backgroundColor: `color-mix(in oklab, ${hueOf(seed)} 22%, var(--card))` };
}

/** 头像只有一个字母,读屏念不出含义 —— 标签说清是「账号」加名字。 */
function avatarLabel(label: string, name: string): string {
  return name ? `${label} · ${name}` : label;
}

export function AccountNav({
  locale,
  loginLabel,
  accountLabel,
  signOutLabel,
}: {
  locale: Locale;
  loginLabel: string;
  accountLabel: string;
  signOutLabel: string;
}) {
  // undefined = 还在问 /me;null = 问过了,没登录。两份数据都走查询缓存:
  // 登录 / 退出 / 改资料之后由 invalidateQueries 通知,而不是只有挂载时问一次。
  const viewer = useViewer();
  const unreadQuery = useUnreadCount();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key === "Escape") setOpen(false);
        return;
      }
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  const signOut = async () => {
    setSigningOut(true);
    try {
      await cloudAccount.logout();
    } catch {
      // 服务端撤销失败也要离开这一页:留着本地缓存比留着 cookie 更糟。
    }
    await invalidateAfterSignOut(queryClient);
    setOpen(false);
    router.push(`/${locale}/login`);
    router.refresh();
  };
  // 注意不能用 `viewer.data ?? ...` —— 401 时 data 是 **null**(「问过了,没登录」),
  // 空值合并会把它当成「还没问过」,登录按钮就永远不出现。undefined 才是加载中。
  const user = viewer.data !== undefined ? viewer.data : viewer.isError ? null : undefined;
  // 没登录 / 401 时保持 0(角标就不出现)。
  const unread = unreadQuery.data ?? 0;

  if (user === undefined) return null;
  if (user) {
    // 名字决定首字,也决定底色 —— 邮箱只取 @ 前面的部分,不会被渲染出来。
    const name = accountName(user);
    const badge = formatUnreadBadge(unread);
    const label = badge ? `${avatarLabel(accountLabel, name)} · ${badge}` : avatarLabel(accountLabel, name);
    return (
      <div ref={menuRef} className="relative shrink-0">
        <button
          type="button"
          aria-label={label}
          aria-haspopup="menu"
          aria-expanded={open}
          title={label}
          onClick={() => setOpen((value) => !value)}
          className="relative inline-flex size-9 items-center justify-center rounded-full text-sm font-semibold text-ink transition-shadow hover:ring-2 hover:ring-ring/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
          style={avatarStyle(name || user.id)}
        >
          {initialOf(name)}
          {badge && (
            <span
              aria-hidden
              className="absolute -top-0.5 -right-0.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-destructive px-1 text-[10px] leading-none font-semibold text-background tabular-nums ring-2 ring-background"
            >
              {badge}
            </span>
          )}
        </button>
        {open && (
          <div
            role="menu"
            aria-label={accountLabel}
            className="absolute right-0 top-full z-50 mt-2 w-44 overflow-hidden rounded-lg border border-border bg-background p-1 shadow-lg"
          >
            <Link
              role="menuitem"
              href={`/${locale}/dashboard`}
              onClick={() => setOpen(false)}
              className="flex items-center rounded-md px-3 py-2 text-sm text-foreground transition-colors hover:bg-secondary"
            >
              {accountLabel}
            </Link>
            <button
              type="button"
              role="menuitem"
              disabled={signingOut}
              onClick={() => void signOut()}
              className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-50"
            >
              <LogOut size={14} aria-hidden />
              {signingOut ? "…" : signOutLabel}
            </button>
          </div>
        )}
      </div>
    );
  }
  return (
    <Button
      asChild
      variant="outline"
      size="lg"
      className="hidden rounded-full border-border bg-transparent px-4 text-muted-foreground hover:bg-secondary hover:text-foreground sm:inline-flex"
    >
      <Link href={`/${locale}/login`}>{loginLabel}</Link>
    </Button>
  );
}
