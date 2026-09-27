import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";

import { AdminPage } from "@/components/community/admin";
import { CommunityUnavailable, PageShell } from "@/components/community/shell";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { communityEnabled } from "@/lib/community/server";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return { title: `${getMessages(locale).admin.title} · Mosael`, robots: { index: false } };
}

/** 角色在浏览器里判断只是为了给对的界面;真正的权限检查在社区服务的 `/admin/*` 上。 */
export default async function Admin({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  await connection();
  if (!communityEnabled()) return <CommunityUnavailable locale={locale} />;
  const t = getMessages(locale);
  return (
    <PageShell eyebrow={t.community.name} title={t.admin.title} lede={t.admin.lede}>
      <AdminPage locale={locale} />
    </PageShell>
  );
}
