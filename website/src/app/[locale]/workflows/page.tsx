import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowUpRight, Download, Film, Scissors } from "lucide-react";

import { PageHero } from "@/components/page-hero";
import { Shot } from "@/components/shot";
import { isLocale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { listWorkflows } from "@/lib/registry";
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
      <PageHero title={t.title} lede={t.lede} />
      <section className="bg-paper" aria-labelledby="workflow-library">
        <div className="mx-auto max-w-[88rem] px-5 pb-24 sm:px-8 sm:pb-32">
          <div className="mb-10 flex flex-wrap items-end justify-between gap-4">
            <div>
              <h2 id="workflow-library" className="m-0 font-display text-3xl font-semibold tracking-tight sm:text-4xl">{t.galleryTitle}</h2>
              <p className="mb-0 mt-3 max-w-2xl text-muted-foreground">{t.galleryBody}</p>
            </div>
            <Link href="#import-workflow" className="text-sm font-semibold text-primary underline-offset-4 hover:underline">{t.importTitle}</Link>
          </div>
          <ul className="m-0 grid list-none gap-x-12 p-0 lg:grid-cols-2">
            {workflows.map((workflow) => {
              const Icon = workflow.id === "full_video_generation" ? Film : Scissors;
              return (
                <li key={workflow.id} className="flex min-w-0 flex-col border-t border-border py-8">
                  <div className="mb-5 flex items-center justify-between gap-3 text-sm text-muted-foreground">
                    <span className="inline-flex items-center gap-2 text-primary"><Icon className="size-5" aria-hidden />{t.official}</span>
                    <span>{t.templateVersion} {workflow.version}</span>
                  </div>
                  <h3 className="m-0 font-display text-2xl font-semibold tracking-tight">{workflow.name}</h3>
                  <p className="mb-6 mt-3 leading-7 text-muted-foreground">{workflow.summary}</p>
                  <ol className="mb-6 flex list-none flex-wrap gap-x-4 gap-y-2 p-0 text-sm" aria-label={t.stages}>
                    {workflow.stages.map((stage, index) => <li key={stage} className="flex items-center gap-2"><span className="text-primary">{index + 1}.</span>{stage}</li>)}
                  </ol>
                  <div className="mb-7">
                    <h4 className="mb-2 mt-0 text-sm font-semibold">{t.requirements}</h4>
                    <ul className="m-0 list-disc space-y-1 pl-5 text-sm leading-6 text-muted-foreground">{workflow.requires.map((item) => <li key={item}>{item}</li>)}</ul>
                  </div>
                  <div className="mt-auto flex flex-wrap items-center justify-between gap-4">
                    <span className="text-sm text-muted-foreground">{workflow.nodes} {t.nodes} · {workflow.author}</span>
                    <a href={workflow.graph} download className="inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-85" aria-label={`${t.download}: ${workflow.name}`}>
                      <Download className="size-4" aria-hidden />{t.download}
                    </a>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      </section>
      <section id="import-workflow" className="scroll-mt-24 bg-secondary/40" aria-labelledby="import-title">
        <div className="mx-auto grid max-w-[88rem] gap-10 px-5 py-20 sm:px-8 lg:grid-cols-[0.8fr_1.2fr] lg:gap-20">
          <div>
            <h2 id="import-title" className="m-0 font-display text-3xl font-semibold tracking-tight">{t.importTitle}</h2>
            <p className="mt-4 leading-7 text-muted-foreground">{t.importNote}</p>
            <Link href={localePath(locale, "/docs/guides/workflows")} className="text-sm font-semibold text-primary hover:underline">{t.guideLink}</Link>
          </div>
          <ol className="m-0 list-none space-y-6 p-0">{t.importSteps.map((step, index) => <li key={step.title} className="flex items-start gap-4"><span className="grid size-8 shrink-0 place-items-center rounded-full border border-border text-sm font-semibold text-primary">{index + 1}</span><div><h3 className="m-0 text-base font-semibold">{step.title}</h3><p className="mb-0 mt-2 text-sm leading-7 text-muted-foreground">{step.body}</p></div></li>)}</ol>
        </div>
      </section>
      <section className="bg-paper">
        <div className="mx-auto max-w-[88rem] px-5 py-20 sm:px-8">
          <Shot src="/media/screens/workflows.png" alt={t.shotAlt} caption={t.shotCaption} framed />
          <p className="mb-0 mt-10 flex flex-wrap items-center justify-between gap-4 text-sm text-muted-foreground"><span>{t.contributeBody}</span><a href={`${SITE.repo}/issues/new`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 font-semibold text-primary hover:underline">{t.contribute}<ArrowUpRight className="size-4" aria-hidden /></a></p>
        </div>
      </section>
    </>
  );
}
