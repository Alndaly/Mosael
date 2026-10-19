import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { AccountShell } from "@/components/account/account-shell";
import { LoginForm } from "@/components/account/login-form";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { pageMetadata } from "@/lib/seo";

type Params = Promise<{ locale: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).account;
  return {
    ...pageMetadata({ locale, path: "/login", title: t.loginSeoTitle, description: t.loginLede }),
    robots: { index: false, follow: false },
  };
}

export default async function LoginPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: Promise<{ registered?: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const { registered } = await searchParams;
  const t = getMessages(locale).account;
  return (
    <AccountShell locale={locale} copy={t} title={t.loginTitle} lede={t.loginLede}>
      <LoginForm locale={locale} copy={t} registered={registered === "1"} />
    </AccountShell>
  );
}
