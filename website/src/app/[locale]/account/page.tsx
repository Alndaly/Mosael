import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";

import { AccountPage } from "@/components/community/account";
import { CommunityUnavailable, PageShell } from "@/components/community/shell";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { communityEnabled } from "@/lib/community/server";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return { title: `${getMessages(locale).account.title} · Mosael`, robots: { index: false } };
}

/** 外壳在服务端,内容在浏览器里按登录态取(令牌只在内存里)。 */
export default async function Account({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  await connection();
  if (!communityEnabled()) return <CommunityUnavailable locale={locale} />;
  const t = getMessages(locale);
  return (
    <PageShell eyebrow={t.community.name} title={t.account.title} lede={t.account.lede}>
      <AccountPage locale={locale} />
    </PageShell>
  );
}
