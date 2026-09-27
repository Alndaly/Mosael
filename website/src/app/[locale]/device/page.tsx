import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";

import { DeviceApproval } from "@/components/community/device-approval";
import { CommunityUnavailable, PageShell } from "@/components/community/shell";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { communityEnabled } from "@/lib/community/server";

type Props = { params: Promise<{ locale: string }>; searchParams: Promise<{ code?: string | string[] }> };

export async function generateMetadata({ params }: Pick<Props, "params">): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return { title: `${getMessages(locale).device.title} · Mosael`, robots: { index: false } };
}

/** 桌面应用发起设备授权时打开的那一页(`?code=XXXX-XXXX` 预填)。 */
export default async function DevicePage({ params, searchParams }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  await connection();
  if (!communityEnabled()) return <CommunityUnavailable locale={locale} />;
  const t = getMessages(locale);
  const { code } = await searchParams;
  return (
    <PageShell eyebrow={t.community.name} title={t.device.title} narrow>
      <DeviceApproval locale={locale} initialCode={typeof code === "string" ? code : ""} />
    </PageShell>
  );
}
