import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowUpRight } from "lucide-react";

import { PageHero } from "@/components/page-hero";
import { Reveal } from "@/components/reveal";
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
  return { title: `${t.title} · Open Studio`, description: t.lede };
}

export default async function WorkflowsPage({ params }: { params: Params }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = getMessages(locale).workflows;
  const workflows = listWorkflows();

  return (
    <>
      <PageHero title={t.title} lede={t.lede} />

      <section className="border-b-2 border-ink bg-paper">
        <div className="mx-auto max-w-[96rem] px-5 py-20 sm:px-8">
          <Reveal>
            <Shot src="/media/screens/workflows.png" alt={t.shotAlt} caption={t.shotCaption} framed />
          </Reveal>
        </div>
      </section>

      {/* 画廊。空的时候不摆占位卡片 —— 那是在假装已经有内容。 */}
      <section className="border-b-2 border-ink bg-invert text-invert-foreground">
        <div className="mx-auto max-w-[96rem] px-5 py-20 sm:px-8">
          <h2 className="mt-0 mb-12 font-display text-[clamp(1.5rem,4vw,2.75rem)] font-extrabold tracking-tight">
            {t.galleryTitle}
          </h2>

          {workflows.length === 0 ? (
            <Reveal className="max-w-3xl border-2 border-invert-foreground p-8 sm:p-12">
              <h3 className="mt-0 mb-4 font-display text-2xl font-bold tracking-tight">{t.galleryEmptyTitle}</h3>
              <p className="mt-0 mb-8 text-invert-foreground/70">{t.galleryEmptyBody}</p>
              <a
                className="inline-flex items-center gap-2 border-2 border-invert-foreground bg-flame px-6 py-3 font-bold text-primary-foreground transition-transform hover:-translate-y-1"
                href={`${SITE.repo}/issues/new`}
                target="_blank"
                rel="noreferrer"
              >
                {t.contribute}
                <ArrowUpRight className="size-4" />
              </a>
            </Reveal>
          ) : (
            <ul className="m-0 grid list-none gap-6 p-0 lg:grid-cols-3">
              {workflows.map((workflow) => (
                <li key={workflow.id} className="m-0 border-2 border-invert-foreground p-6">
                  <h3 className="m-0 font-display text-lg font-bold tracking-tight">{workflow.name}</h3>
                  <p className="mt-3 mb-4 text-invert-foreground/70">{workflow.summary}</p>
                  <p className="m-0 font-mono text-xs text-invert-foreground/60">
                    {workflow.nodes} · {workflow.requires.join(" · ")} · {workflow.author}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* 条目形状:编号 + 字段名 + 一句解释,像一份表格的说明,而不是四张卡。 */}
      <section className="bg-paper">
        <div className="mx-auto max-w-[96rem] px-5 py-20 sm:px-8">
          <h2 className="mt-0 mb-12 font-display text-[clamp(1.5rem,4vw,2.75rem)] font-extrabold tracking-tight">
            {t.fieldsTitle}
          </h2>
          <dl className="m-0 border-t-2 border-ink">
            {t.fields.map((field, index) => (
              <Reveal
                key={field.name}
                delay={index * 60}
                className="grid gap-2 border-b-2 border-ink py-6 sm:grid-cols-12 sm:items-baseline sm:gap-8"
              >
                <span className="font-mono text-xs font-bold tracking-widest text-flame uppercase sm:col-span-1">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <dt className="font-display text-lg font-bold tracking-tight sm:col-span-4">{field.name}</dt>
                <dd className="m-0 text-muted-foreground sm:col-span-7">{field.body}</dd>
              </Reveal>
            ))}
          </dl>

          <p className="mt-12 mb-0 text-sm font-bold">
            <Link className="border-b-2 border-flame pb-0.5" href={localePath(locale, "/docs/guides/workflows")}>
              {t.guideLink}
            </Link>
          </p>
        </div>
      </section>
    </>
  );
}
