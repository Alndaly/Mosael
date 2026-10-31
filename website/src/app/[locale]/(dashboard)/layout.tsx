import Link from "next/link";
import { notFound } from "next/navigation";

import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

/**
 * 个人控制台的独立外壳。
 *
 * `/dashboard` 是登录后的管理页面，不属于公开站点的营销导航。此前它住在 `(site)` 里，
 * 被迫继承站头 / 站尾和给悬浮站头留的 5rem 顶边距 —— 管理页的页头还得用负 margin 钻回去。
 * 现在单独成组：URL 仍是 `/<locale>/dashboard`，但只保留一个返回站内的小入口，不再渲染公开站头 / 站尾。
 *
 * 分组名带括号，不进入 URL；`(site)` / `(auth)` / `(admin)` / `(dashboard)` 各自拥有自己的 layout。
 */
export default async function DashboardLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = getMessages(locale);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border bg-paper">
        <div className="mx-auto flex h-16 max-w-[76rem] items-center justify-between gap-4 px-5 sm:px-8">
          <Link href={`/${locale}`} className="font-display text-lg font-bold tracking-tight">
            Mosael
          </Link>
          <Link
            href={`/${locale}/community`}
            className="text-sm text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
          >
            {t.community.backToCommunity}
          </Link>
        </div>
      </header>
      <main id="main">{children}</main>
    </div>
  );
}
