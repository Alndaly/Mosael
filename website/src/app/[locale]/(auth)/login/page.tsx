import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { AccountShell } from "@/components/account/account-shell";
import { LoginForm } from "@/components/account/login-form";
import { RememberLoginReturn } from "@/components/community/login-return";
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
  searchParams: Promise<{ registered?: string; oauth_error?: string; next?: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const { registered, oauth_error: oauthError, next } = await searchParams;
  const t = getMessages(locale).account;
  return (
    <AccountShell locale={locale} copy={t} title={t.loginTitle} lede={t.loginLede}>
      {/* 从社区点「登录」过来时带着 next:登录成功(表单固定去账号页)后由账号页接回社区。 */}
      <RememberLoginReturn locale={locale} next={next} />
      <LoginForm locale={locale} copy={t} registered={registered === "1"} oauthError={oauthError ?? ""} />
    </AccountShell>
  );
}
