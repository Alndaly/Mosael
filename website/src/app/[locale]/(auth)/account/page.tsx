import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { AccountShell } from "@/components/account/account-shell";
import { AccountView } from "@/components/account/account-view";
import { ResumeLoginReturn } from "@/components/community/login-return";
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
  searchParams: Promise<{ oauth?: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const { oauth } = await searchParams;
  const t = getMessages(locale).account;

  return (
    <AccountShell locale={locale} copy={t} title={t.accountTitle} lede={t.accountLede} wide>
      {/* 登录前从社区带来的 next(见 components/community/login-return.tsx):会话建立后回到那一页。 */}
      <ResumeLoginReturn locale={locale} />
      <AccountView
        locale={locale}
        copy={t}
        oauthOutcome={oauth === "created" || oauth === "existing" ? oauth : ""}
      />
    </AccountShell>
  );
}
