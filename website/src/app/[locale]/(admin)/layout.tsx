import Link from "next/link";
import { notFound } from "next/navigation";

import { isLocale } from "@/i18n/config";

/**
 * MosaelCloud 管理端的独立外壳。
 *
 * 这里**刻意不套 `(site)` 的站头 / 站尾**：管理台不是 Mosael 产品页,也不是社区页面;
 * 它只通过明确的 `/locale/admin` 地址进入,不把入口挂在公开站头上,避免普通用户误点。
 * URL 不受分组名影响,仍然是 `/<locale>/admin`。
 */
export default async function AdminLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  return (
    <div className="dark min-h-screen bg-background text-foreground">
      <header className="border-b border-border bg-background">
        <div className="mx-auto flex h-14 max-w-[88rem] items-center justify-between gap-4 px-5 sm:px-8">
          <div className="flex min-w-0 items-baseline gap-2">
            <Link href={`/${locale}`} className="font-display text-sm font-bold tracking-tight">
              MOSAEL
            </Link>
            <span className="text-xs text-muted-foreground">MosaelCloud Admin</span>
          </div>
          <Link
            href={`/${locale}`}
            className="text-xs font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            返回 Mosael
          </Link>
        </div>
      </header>
      <main id="main">{children}</main>
    </div>
  );
}
