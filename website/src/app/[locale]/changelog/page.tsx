import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ArrowUpRight } from "lucide-react";

import { PageHero } from "@/components/page-hero";
import { isLocale } from "@/i18n/config";
import { listReleases } from "@/lib/releases";
import { releaseCopy } from "@/lib/release-copy";
import { releaseHighlights } from "@/lib/release-data";
import { SITE } from "@/lib/site";

export const revalidate = 3600;
type Params = Promise<{ locale: string }>;
const copy = {
  zh: { title: "更新日志", lede: "每次发布，都向更顺畅的创作靠近。查看新增功能、问题修复与升级说明。", stable: "正式版", beta: "预发版", latest: "最新发布", notes: "完整说明与下载", history: "查看更早的版本", empty: "此版本的详细变更请查看发布说明。", offline: "暂时无法同步发布记录，以下展示已保存的记录，保存于", sync: "按发布时间排列，正式版与预发版均收录。发布记录每小时同步，最近展示 30 个版本。" },
  en: { title: "Changelog", lede: "Follow each release: new capabilities, fixes and everything you need to know before upgrading.", stable: "Stable", beta: "Pre-release", latest: "Latest release", notes: "Full notes and downloads", history: "Browse earlier releases", empty: "See the release notes for the full list of changes.", offline: "Release sync is temporarily unavailable. Showing saved records from", sync: "Published releases, newest first, including stable and pre-release versions. Synced hourly; showing the latest 30 releases." },
};

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return { title: `${copy[locale].title} · Mosael`, description: copy[locale].lede };
}

export default async function ChangelogPage({ params }: { params: Params }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = copy[locale];
  const { releases, offline, snapshotDate } = await listReleases();
  const formatDate = (value: string) => new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en", { dateStyle: "long", timeZone: "UTC" }).format(new Date(value));
  return <>
    <PageHero title={t.title} lede={t.lede} />
    <section className="bg-paper">
      <div className="mx-auto max-w-[88rem] px-5 pb-24 sm:px-8">
        <p className="mb-10 mt-0 max-w-3xl text-sm leading-7 text-muted-foreground">{offline ? `${t.offline} ${formatDate(snapshotDate)}.` : t.sync}</p>
        <ol className="m-0 list-none border-t border-border p-0">
          {releases.map((release, index) => {
            const highlights = releaseCopy[release.tag]?.[locale] ?? releaseHighlights(release.body);
            return <li key={release.tag} id={release.tag} className="scroll-mt-24 border-b border-border py-10 sm:py-14">
              <article className="grid gap-6 md:grid-cols-[13rem_minmax(0,1fr)] lg:gap-16" aria-labelledby={`title-${release.tag}`}>
                <div>
                  <time dateTime={release.publishedAt} className="text-sm text-muted-foreground">{formatDate(release.publishedAt)}</time>
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-xs font-medium"><span className="rounded-full bg-secondary px-3 py-1.5">{release.prerelease ? t.beta : t.stable}</span>{index === 0 && <span className="text-primary">{t.latest}</span>}</div>
                </div>
                <div className="min-w-0 max-w-3xl">
                  <h2 id={`title-${release.tag}`} className="mb-5 mt-0 font-display text-3xl font-semibold tracking-tight"><a href={`#${release.tag}`} className="hover:text-primary">{release.tag}</a></h2>
                  {highlights.length ? <ul className="mb-6 list-disc space-y-3 pl-5 leading-7 text-muted-foreground">{highlights.map((line, i) => <li key={i} className="break-words">{line}</li>)}</ul> : <p className="text-muted-foreground">{t.empty}</p>}
                  <a href={release.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-sm font-semibold text-primary hover:underline">{t.notes}<ArrowUpRight className="size-4" aria-hidden /></a>
                </div>
              </article>
            </li>;
          })}
        </ol>
        <a href={`${SITE.repo}/releases`} target="_blank" rel="noreferrer" className="mt-10 inline-flex items-center gap-2 text-sm font-semibold text-primary hover:underline">{t.history}<ArrowUpRight className="size-4" aria-hidden /></a>
      </div>
    </section>
  </>;
}
