import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";

import { ResetPasswordForm } from "@/components/community/auth/auth-forms";
import { CommunityUnavailable, PageShell } from "@/components/community/shell";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { communityEnabled } from "@/lib/community/server";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return { title: `${getMessages(locale).auth.resetTitle} · Mosael`, robots: { index: false } };
}

export default async function ResetPasswordPage({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  await connection();
  if (!communityEnabled()) return <CommunityUnavailable locale={locale} />;
  const t = getMessages(locale);
  return (
    <PageShell eyebrow={t.community.name} title={t.auth.resetTitle} lede={t.auth.resetLede} narrow>
      <ResetPasswordForm locale={locale} />
    </PageShell>
  );
}
