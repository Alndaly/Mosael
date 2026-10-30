import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { AccountShell } from "@/components/account/account-shell";
import { MfaChallenge } from "@/components/account/mfa-challenge";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { pageMetadata } from "@/lib/seo";

type Params = Promise<{ locale: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).account;
  return {
    ...pageMetadata({ locale, path: "/mfa", title: t.mfaTitle, description: t.mfaLede }),
    robots: { index: false, follow: false },
  };
}

/** OAuth 回调带着 ticket 回到这里；邮箱 / 密码登录则直接在登录表单内完成第二步。 */
export default async function MfaPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: Promise<{ ticket?: string | string[] }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const raw = (await searchParams).ticket;
  const ticket = Array.isArray(raw) ? raw[0] : raw;
  if (!ticket) redirect(`/${locale}/login`);
  const t = getMessages(locale).account;
  return (
    <AccountShell locale={locale} copy={t} title={t.mfaTitle} lede={t.mfaLede}>
      <MfaChallenge locale={locale} copy={t} ticket={ticket} />
    </AccountShell>
  );
}
