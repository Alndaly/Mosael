import type { Metadata } from "next";

import { SubmitPage } from "@/components/community/submit-page";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return { title: `${getMessages(locale).submit.workflowTitle} · Mosael`, robots: { index: false } };
}

/** 静态段 `new` 优先于 `[slug]`:社区服务要把 `new` 留作保留字,不发给任何条目。 */
export default function NewWorkflowPage({ params }: Props) {
  return <SubmitPage params={params} kind="workflow" />;
}
