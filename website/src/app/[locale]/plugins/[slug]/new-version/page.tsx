import type { Metadata } from "next";

import { SubmitPage } from "@/components/community/submit-page";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

type Props = { params: Promise<{ locale: string; slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return { title: `${getMessages(locale).submit.versionTitle} · Mosael`, robots: { index: false } };
}

/** 作者给自己的插件发新版本(同一个插件 id);新版本同样先进审核队列。 */
export default function NewPluginVersionPage({ params }: Props) {
  return <SubmitPage params={params} kind="plugin" />;
}
