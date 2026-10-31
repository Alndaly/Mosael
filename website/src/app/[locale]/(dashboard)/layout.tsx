import { notFound } from "next/navigation";

import { isLocale } from "@/i18n/config";

/**
 * 个人控制台的独立外壳。
 *
 * `/dashboard` 是登录后的管理页面，不继承公开站点的营销导航。布局只负责把页面交给
 * `DashboardView` 里的侧栏工作区；品牌、分区导航和账号区块都在那层，随分区状态一起更新。
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

  return <main id="main">{children}</main>;
}
