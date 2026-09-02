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
  return { title: `${t.title} · Mosael`, description: t.lede };
}

export default async function WorkflowsPage({ params }: { params: Params }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = getMessages(locale).workflows;
  const workflows = listWorkflows();

  return (
    <>
      <PageHero title={t.title} lede={t.lede} />

      <section className="bg-paper">
        <div className="mx-auto max-w-[88rem] px-5 pb-24 sm:px-8 sm:pb-32">
          <Reveal>
            <Shot src="/media/screens/workflows.png" alt={t.shotAlt} caption={t.shotCaption} framed />
          </Reveal>
        </div>
      </section>

      {/* 画廊。空的时候不摆占位卡片 —— 那是在假装已经有内容。 */}
      <section className="bg-[#17141f] text-[#fbf9ff]">
        <div className="mx-auto max-w-[88rem] px-5 py-24 sm:px-8 sm:py-32">
          <h2 className="mt-0 mb-14 max-w-[14ch] font-display text-[clamp(2.5rem,6vw,5rem)] leading-[0.96] font-[700] tracking-[-0.05em]">
            {t.galleryTitle}
          </h2>

          {workflows.length === 0 ? (
            <Reveal className="grid max-w-5xl gap-8 border-t border-white/15 pt-8 md:grid-cols-12 md:items-end">
              <div className="md:col-span-8"><h3 className="mt-0 mb-4 font-display text-2xl font-semibold tracking-[-0.025em]">{t.galleryEmptyTitle}</h3><p className="m-0 max-w-2xl text-white/58">{t.galleryEmptyBody}</p></div>
              <a
                className="inline-flex min-h-12 items-center justify-center gap-2 rounded-full bg-primary px-6 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-85 md:col-span-4 md:justify-self-end"
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
                <li key={workflow.id} className="m-0 border-t border-white/15 py-6">
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
        <div className="mx-auto max-w-[88rem] px-5 py-24 sm:px-8 sm:py-32">
          <h2 className="mt-0 mb-14 max-w-[14ch] font-display text-[clamp(2.5rem,6vw,5rem)] leading-[0.96] font-[700] tracking-[-0.05em]">
            {t.fieldsTitle}
          </h2>
          <dl className="m-0 border-t border-border">
            {t.fields.map((field, index) => (
              <Reveal
                key={field.name}
                delay={index * 60}
                className="grid gap-2 border-b border-border py-7 sm:grid-cols-12 sm:items-baseline sm:gap-8"
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
            <Link className="inline-flex items-center gap-2 text-primary hover:opacity-70" href={localePath(locale, "/docs/guides/workflows")}>
              {t.guideLink}
            </Link>
          </p>
        </div>
      </section>
    </>
  );
}
