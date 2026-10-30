import { notFound } from "next/navigation";

import { isLocale } from "@/i18n/config";

/**
 * MosaelCloud 管理端的独立外壳。
 *
 * 管理台不套 `(site)` 的公开站头 / 站尾；品牌和导航都在左侧 Sidebar 里，
 * 页面顶部不再叠一条全局 header。URL 仍然是 `/<locale>/admin`。
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
    <div className="min-h-screen bg-background text-foreground">
      <main id="main">{children}</main>
    </div>
  );
}
