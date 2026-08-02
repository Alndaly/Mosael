import { notFound, redirect } from "next/navigation";

import { isLocale } from "@/i18n/config";
import { docHref, firstDoc } from "@/lib/docs";

/** `/docs` 自己不承载内容 —— 直接送到第一篇,免得多一个"目录页"要维护。 */
export default async function DocsIndex({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  redirect(docHref(locale, firstDoc(locale)));
}
