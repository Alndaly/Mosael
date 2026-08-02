import { notFound } from "next/navigation";

import { DocsSidebar, type SidebarGroup } from "@/components/docs-sidebar";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { DOC_SECTIONS, docHref, listDocs } from "@/lib/docs";

/**
 * 文档区的两栏骨架。
 *
 * 侧边栏在桌面端常驻(`sticky`,跟着页面滚但自己不动),窄屏收成正文上方的一段目录 ——
 * 不做抽屉:一个需要点两次才能看见目录的文档站,不如把目录直接摊开。
 */
export default async function DocsLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = getMessages(locale);
  const docs = listDocs(locale);
  const groups: SidebarGroup[] = DOC_SECTIONS.map((section) => ({
    label: t.docs.sections[section],
    items: docs
      .filter((doc) => doc.section === section)
      .map((doc) => ({ href: docHref(locale, doc), title: doc.title })),
  })).filter((group) => group.items.length > 0);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-10 px-6 py-12 sm:px-8 lg:flex-row lg:gap-14">
      <div className="lg:w-52 lg:shrink-0">
        <DocsSidebar groups={groups} className="lg:sticky lg:top-24" />
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
