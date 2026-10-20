import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { WorkflowBrowser } from "@/components/community/browse";
import { CommunityHeader } from "@/components/community/community-header";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { listPlugins, listWorkflows } from "@/lib/registry";
import { pageMetadata } from "@/lib/seo";
import { localePath } from "@/i18n/config";

type Params = Promise<{ locale: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).workflows;
  return pageMetadata({ locale, path: "/workflows", title: t.seoTitle, description: t.seoDescription, keywords: t.keywords });
}

export default async function WorkflowsPage({ params }: { params: Params }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = getMessages(locale).workflows;
  const workflows = listWorkflows(locale);

  return (
    <>
      <CommunityHeader
        locale={locale}
        active="workflows"
        counts={{ plugins: listPlugins(locale).length, workflows: workflows.length }}
        title={t.heading}
        lede={t.lede}
        // 「分享你的工作流」现在有真的落点:上传页(传一份 .json 就出现在社区)。
        // 不再是「去 GitHub 提 issue」——那是我们还没有上传功能时的替代品。
        contribute={{ label: t.contribute, href: localePath(locale, "/community/upload") }}
      />
      <section className="bg-paper">
        <div className="mx-auto max-w-[76rem] px-5 py-10 sm:px-8 sm:pb-24">
          <WorkflowBrowser locale={locale} workflows={workflows} />
        </div>
      </section>
    </>
  );
}
