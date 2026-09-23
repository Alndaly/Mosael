import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { CheckCircle2, Download } from "lucide-react";

import { WorkflowCard } from "@/components/community/browse";
import { ActionLink, DetailBody, DetailHeader, InfoList, Section, SideCard, Steps } from "@/components/community/detail";
import { WorkflowTile } from "@/components/community/tile";
import { LOCALES, isLocale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { findWorkflow, listWorkflows } from "@/lib/registry";

/** 每个模板 × 每种语言,构建期全出好 —— 数据来自应用内置模板导出的目录(public/workflows/catalog.json)。 */
export function generateStaticParams() {
  return LOCALES.flatMap((locale) => listWorkflows(locale).map((workflow) => ({ locale, slug: workflow.slug })));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; slug: string }>;
}): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!isLocale(locale)) return {};
  const workflow = findWorkflow(slug, locale);
  if (!workflow) return {};
  return { title: `${workflow.name} · ${getMessages(locale).workflows.title}`, description: workflow.summary };
}

export default async function WorkflowDetailPage({
  params,
}: {
  params: Promise<{ locale: string; slug: string }>;
}) {
  const { locale, slug } = await params;
  if (!isLocale(locale)) notFound();
  const workflow = findWorkflow(slug, locale);
  if (!workflow) notFound();
  const t = getMessages(locale);
  const more = listWorkflows(locale)
    .filter((other) => other.slug !== workflow.slug)
    .slice(0, 3);

  return (
    <>
      <DetailHeader
        locale={locale}
        section={{ label: t.workflows.title, href: "/workflows" }}
        tile={<WorkflowTile id={workflow.id} size="lg" />}
        name={workflow.name}
        author={workflow.author}
        version={`${t.workflows.templateVersion} ${workflow.version}`}
        official={workflow.author === "Mosael"}
        summary={workflow.summary}
        actions={
          <>
            <ActionLink href={workflow.graph} primary download>
              <Download className="size-4" aria-hidden />
              {t.workflows.download}
            </ActionLink>
            {/* 深链只导航、不执行:打开工作流社区、选中这个模板,添加副本仍由人点。 */}
            <ActionLink href={`mosael://open?view=workflows&template=${encodeURIComponent(workflow.id)}`}>{t.community.openInApp}</ActionLink>
          </>
        }
      />
      <DetailBody
        main={
          <>
            <Section id="pipeline" title={t.workflows.stagesTitle} count={workflow.stages.length}>
              {/* 竖着的一条线串起每一步:工作流本来就是「先这个、再那个」。 */}
              <ol className="m-0 grid list-none gap-0 p-0">
                {workflow.stages.map((stage, index) => (
                  <li key={stage} className="relative grid grid-cols-[2rem_minmax(0,1fr)] gap-3 pb-5 last:pb-0">
                    {index < workflow.stages.length - 1 && (
                      <span aria-hidden className="absolute top-8 bottom-0 left-4 w-px -translate-x-1/2 bg-border" />
                    )}
                    <span className="grid size-8 place-items-center rounded-full border border-primary/30 bg-brand-soft font-mono text-xs font-bold text-primary tabular-nums">
                      {index + 1}
                    </span>
                    <span className="pt-1 leading-6">{stage}</span>
                  </li>
                ))}
              </ol>
            </Section>

            <Section id="requirements" title={t.workflows.requirementsTitle}>
              <ul className="m-0 grid list-none gap-2.5 p-0 text-sm">
                {workflow.requires.map((item) => (
                  <li key={item} className="flex items-start gap-2.5 leading-6">
                    <CheckCircle2 className="mt-1 size-4 shrink-0 text-primary" aria-hidden />
                    {item}
                  </li>
                ))}
              </ul>
            </Section>
          </>
        }
        aside={
          <>
            <SideCard title={t.workflows.importTitle}>
              <Steps steps={t.workflows.importSteps} />
              <p className="mt-5 mb-0 text-xs leading-5 text-muted-foreground">{t.workflows.importNote}</p>
              <p className="mt-3 mb-0 text-xs text-muted-foreground">
                {t.community.noApp}{" "}
                <a className="font-semibold text-primary hover:underline" href={localePath(locale, "/docs/start/download")}>
                  {t.community.getApp}
                </a>
              </p>
            </SideCard>
            <SideCard title={t.community.info}>
              <InfoList
                rows={[
                  { label: t.community.by, value: workflow.author },
                  { label: t.workflows.templateVersion, value: <span className="font-mono">{workflow.version}</span> },
                  { label: t.workflows.stagesTitle, value: `${workflow.stages.length} ${t.workflows.steps} · ${workflow.nodes} ${t.workflows.nodes}` },
                ]}
              />
            </SideCard>
            <Link className="px-1 text-sm font-semibold text-primary hover:underline" href={localePath(locale, "/docs/guides/workflows")}>
              {t.workflows.guideLink}
            </Link>
          </>
        }
      />
      {more.length > 0 && (
        <section className="border-t border-border bg-secondary/30">
          <div className="mx-auto max-w-[76rem] px-5 py-12 sm:px-8">
            <h2 className="mt-0 mb-6 text-lg font-semibold tracking-tight">{t.workflows.more}</h2>
            <ul className="m-0 grid list-none gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3">
              {more.map((other) => (
                <li key={other.id} className="grid">
                  <WorkflowCard locale={locale} workflow={other} />
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}
    </>
  );
}
