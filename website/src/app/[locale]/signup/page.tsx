import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { AccountShell } from "@/components/account/account-shell";
import { SignupForm } from "@/components/account/signup-form";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { pageMetadata } from "@/lib/seo";

type Params = Promise<{ locale: string }>;

/**
 * 私有页:注册 / 登录 / 账号都属于**账号**,不是给搜索引擎的内容。
 * 仍然走 pageMetadata 出标题与自己的 canonical(seo.test.mjs 盯着每个 page.tsx),
 * 只是额外声明 noindex。
 */
export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).account;
  return {
    ...pageMetadata({ locale, path: "/signup", title: t.signupSeoTitle, description: t.signupLede }),
    robots: { index: false, follow: false },
  };
}

export default async function SignupPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: Promise<{ oauth_error?: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const { oauth_error: oauthError } = await searchParams;
  const t = getMessages(locale).account;
  return (
    <AccountShell locale={locale} copy={t} title={t.signupTitle} lede={t.signupLede}>
      <SignupForm locale={locale} copy={t} oauthError={oauthError ?? ""} />
    </AccountShell>
  );
}
