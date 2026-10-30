import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { AdminConsole } from "@/components/admin/admin-console";
import { cookieHeader, serverCloud } from "@/components/community/share-server";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { pageMetadata } from "@/lib/seo";

type Params = Promise<{ locale: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).admin;
  return {
    ...pageMetadata({ locale, path: "/admin", title: t.seoTitle, description: t.seoDescription }),
    robots: { index: false, follow: false },
  };
}

export const dynamic = "force-dynamic";

/** MosaelCloud 管理端。真实权限在 Cloud `/admin/*`;这里再挡一次未授权访问。 */
export default async function AdminPage({ params }: { params: Params }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const cookie = await cookieHeader();
  const viewer = await serverCloud(cookie).account.me().then((reply) => reply.user).catch(() => null);
  if (!viewer || viewer.role !== "admin") notFound();
  return <AdminConsole locale={locale} copy={getMessages(locale).admin} />;
}
