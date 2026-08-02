import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

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
    <div className="prose-cn mx-auto max-w-3xl px-6 py-16 font-serif sm:px-8">
      <h1 className="mt-0 mb-5 text-3xl font-semibold sm:text-4xl">{t.title}</h1>
      <p className="mt-0 mb-10 max-w-(--measure) text-lg text-muted-foreground">{t.lede}</p>

      <Shot src="/media/screens/workflows.png" alt={t.shotAlt} caption={t.shotCaption} />

      <h2 className="mt-20 mb-6 text-2xl font-semibold">{t.galleryTitle}</h2>

      {workflows.length === 0 ? (
        // 空画廊比没有画廊更糟 —— 所以这里说清楚"形状已经定好、在等第一条",
        // 而不是摆几个占位卡片假装已经有内容。
        <div className="border-l-2 border-border py-1 pl-5">
          <h3 className="mt-0 mb-2 text-base font-semibold">{t.galleryEmptyTitle}</h3>
          <p className="mt-0 mb-5 max-w-(--measure) text-muted-foreground">{t.galleryEmptyBody}</p>
          <a
            className="font-sans text-sm underline underline-offset-4"
            href={`${SITE.repo}/issues/new`}
            target="_blank"
            rel="noreferrer"
          >
            {t.contribute}
          </a>
        </div>
      ) : (
        <ul className="m-0 list-none border-t border-border/60 p-0">
          {workflows.map((workflow) => (
            <li key={workflow.id} className="m-0 border-b border-border/60 py-6">
              <h3 className="m-0 text-lg font-semibold">{workflow.name}</h3>
              <p className="mt-2 mb-3 max-w-(--measure) text-muted-foreground">{workflow.summary}</p>
              <p className="m-0 font-sans text-xs text-muted-foreground">
                {workflow.nodes} · {workflow.requires.join(" · ")} · {workflow.author}
              </p>
            </li>
          ))}
        </ul>
      )}

      <h2 className="mt-16 mb-6 text-2xl font-semibold">{t.fieldsTitle}</h2>
      <dl className="m-0 border-t border-border/60">
        {t.fields.map((field) => (
          <div key={field.name} className="border-b border-border/60 py-4 sm:flex sm:gap-8">
            <dt className="font-sans text-sm font-medium sm:w-44 sm:shrink-0">{field.name}</dt>
            <dd className="m-0 mt-1.5 text-muted-foreground sm:mt-0">{field.body}</dd>
          </div>
        ))}
      </dl>

      <p className="mt-10 mb-0 font-sans text-sm">
        <Link className="underline underline-offset-4" href={localePath(locale, "/docs/guides/workflows")}>
          {t.guideLink}
        </Link>
      </p>
    </div>
  );
}
