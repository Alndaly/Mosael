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

/** 作者给自己的工作流发新版本;不是作者的话,服务端回 403,表单照原样显示那条错误。 */
export default function NewWorkflowVersionPage({ params }: Props) {
  return <SubmitPage params={params} kind="workflow" />;
}
