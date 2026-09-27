import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { LegalPlaceholder } from "@/components/community/legal-page";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return { title: `${getMessages(locale).legal.termsTitle} · Mosael` };
}

/** 静态页:文本由运营者提供,不依赖社区服务。 */
export default async function TermsPage({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  return <LegalPlaceholder locale={locale} kind="terms" />;
}
