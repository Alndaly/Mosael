import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { AccountShell } from "@/components/account/account-shell";
import { AccountView } from "@/components/account/account-view";
import { ResumeLoginReturn } from "@/components/community/login-return";
import { isLocale, localePath } from "@/i18n/config";
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
  searchParams: Promise<{ user_code?: string; oauth?: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const { user_code, oauth } = await searchParams;
  const t = getMessages(locale).account;

  /*
   * 桌面端绑定(`POST /device/code` 的 `verification_uri`)至今指向
   * `/{locale}/account?user_code=…`。设备那一块已经搬进「我的」控制台,所以带确认码的访问
   * 在这里转过去 —— 桌面端不用改、链接不断,确认码跟着地址走。
   * 其余访问(登录回跳、`?oauth=…`、页脚的「账号」)照旧落在这一页。
   */
  const code = (Array.isArray(user_code) ? user_code[0] : user_code)?.trim();
  if (code) {
    redirect(`${localePath(locale, "/dashboard")}?tab=devices&user_code=${encodeURIComponent(code)}`);
  }

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
