import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";

import { LoginForm } from "@/components/community/auth/auth-forms";
import { CommunityUnavailable, PageShell } from "@/components/community/shell";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { communityEnabled } from "@/lib/community/server";

type Props = { params: Promise<{ locale: string }>; searchParams: Promise<{ next?: string | string[] }> };

export async function generateMetadata({ params }: Pick<Props, "params">): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return { title: `${getMessages(locale).auth.loginTitle} · Mosael`, robots: { index: false } };
}

export default async function LoginPage({ params, searchParams }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  // 社区开没开,看的是**运行时**的环境变量:这一页在请求时渲染,不在构建期定死。
  await connection();
  if (!communityEnabled()) return <CommunityUnavailable locale={locale} />;
  const t = getMessages(locale);
  const { next } = await searchParams;
  return (
    <PageShell eyebrow={t.community.name} title={t.auth.loginTitle} lede={t.auth.loginLede} narrow>
      <LoginForm locale={locale} next={typeof next === "string" ? next : null} />
    </PageShell>
  );
}
