import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { AccountShell } from "@/components/account/account-shell";
import { AccountView } from "@/components/account/account-view";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { pageMetadata } from "@/lib/seo";

type Params = Promise<{ locale: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).account;
  return {
    ...pageMetadata({ locale, path: "/account", title: t.accountSeoTitle, description: t.accountLede }),
    robots: { index: false, follow: false },
  };
}

export default async function AccountPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: Promise<{ user_code?: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const { user_code } = await searchParams;
  const t = getMessages(locale).account;
  return (
    <AccountShell locale={locale} copy={t} title={t.accountTitle} lede={t.accountLede} wide>
      <AccountView locale={locale} copy={t} initialCode={user_code ?? ""} />
    </AccountShell>
  );
}
