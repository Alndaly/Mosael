import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { WorkflowBrowser } from "@/components/community/browse";
import { CommunityHeader } from "@/components/community/community-header";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { listPlugins, listWorkflows } from "@/lib/registry";
import { SITE } from "@/lib/site";

type Params = Promise<{ locale: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).workflows;
  return { title: `${t.title} · Mosael`, description: t.lede };
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
        title={t.title}
        lede={t.lede}
        contribute={{ label: t.contribute, href: `${SITE.repo}/issues/new` }}
      />
      <section className="bg-paper">
        <div className="mx-auto max-w-[76rem] px-5 py-10 sm:px-8 sm:pb-24">
          <WorkflowBrowser locale={locale} workflows={workflows} />
        </div>
      </section>
    </>
  );
}
