import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { AlertTriangle, Download } from "lucide-react";

import { versionLabel, WorkflowCard } from "@/components/community/cards";
import { Sparkline } from "@/components/community/charts";
import { ActionLink, DetailBody, DetailHeader, InfoList, Section, SideCard, Steps, TagLinks, VersionList } from "@/components/community/detail";
import { LikeButton, NewVersionLink, ReportButton } from "@/components/community/item-actions";
import { SafeMarkdown } from "@/components/community/safe-markdown";
import { CommunityDown, CommunityUnavailable, PageShell } from "@/components/community/shell";
import { WorkflowTile } from "@/components/community/tile";
import { WorkflowGraphView } from "@/components/community/workflow-graph";
import { isLocale, localePath, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { ENDPOINTS, browserUrl } from "@/lib/community/endpoints";
import { formatCount, formatDate } from "@/lib/community/format";
import { communityEnabled, serverGet } from "@/lib/community/server";
import { toPlainText } from "@/lib/inline-markdown";
import type { ItemVersion, Page, WorkflowDetail, WorkflowSummary } from "@/lib/community/types";

type Props = { params: Promise<{ locale: string; slug: string }> };

async function load(locale: Locale, slug: string) {
  return serverGet<WorkflowDetail>(ENDPOINTS.items.detail("workflow", slug), locale);
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!isLocale(locale) || !communityEnabled()) return {};
  const result = await load(locale, slug);
  if (!result.ok) return {};
  return { title: `${result.data.title} · ${getMessages(locale).workflows.title}`, description: toPlainText(result.data.summary) };
}

export default async function WorkflowDetailPage({ params }: Props) {
  const { locale, slug } = await params;
  if (!isLocale(locale)) notFound();
  await connection();
  if (!communityEnabled()) return <CommunityUnavailable locale={locale} />;
  const t = getMessages(locale);
  const result = await load(locale, slug);
  if (!result.ok) {
    if (result.error.status === 404 || result.error.status === 410) notFound();
    return (
      <PageShell eyebrow={t.community.name} title={t.workflows.title}>
        <CommunityDown locale={locale} message={result.error.message} />
      </PageShell>
    );
  }
  const item = result.data;
  const [versions, byAuthor] = await Promise.all([
    serverGet<Page<ItemVersion>>(ENDPOINTS.items.versions("workflow", slug), locale),
    serverGet<Page<WorkflowSummary>>(ENDPOINTS.items.list("workflow", { author: item.author.handle, sort: "downloads", limit: 4 }), locale),
  ]);
  const more = byAuthor.ok ? byAuthor.data.items.filter((other) => other.slug !== item.slug).slice(0, 3) : [];
  const templateId = item.graph?.meta?.template_id;

  return (
    <>
      <DetailHeader
        locale={locale}
        section={{ label: t.workflows.title, href: "/workflows" }}
        tile={<WorkflowTile slug={item.slug} cover={item.cover_url} size="lg" />}
        name={item.title}
        author={item.author}
        official={item.official}
        version={versionLabel(item.version)}
        summary={item.summary}
        notice={
          item.has_code ? (
            <p
              role="note"
              className="m-0 flex max-w-[46rem] items-start gap-2.5 rounded-xl border border-[color:var(--tile-4)]/40 bg-[color-mix(in_oklab,var(--tile-4)_10%,var(--card))] px-3.5 py-3 text-sm leading-6"
            >
              <AlertTriangle className="mt-1 size-4 shrink-0 text-[color:var(--tile-4)]" aria-hidden />
              <span>
                <strong className="font-semibold">{t.workflows.codeWarningTitle}</strong>
                {" · "}
                {t.workflows.codeWarning}
              </span>
            </p>
          ) : null
        }
        actions={
          <>
            <ActionLink href={browserUrl(ENDPOINTS.items.download("workflow", item.slug))} primary>
              <Download className="size-4" aria-hidden />
              {t.workflows.download}
            </ActionLink>
            <LikeButton locale={locale} kind="workflow" slug={item.slug} likes={item.likes} />
            {/* 深链只导航、不执行:官方模板在应用里本来就有,直接打开它;社区的要先下载导入。 */}
            {templateId && <ActionLink href={`mosael://open?view=workflows&template=${encodeURIComponent(templateId)}`}>{t.community.openInApp}</ActionLink>}
            <NewVersionLink locale={locale} kind="workflow" slug={item.slug} authorHandle={item.author.handle} />
          </>
        }
      />
      <DetailBody
        main={
          <>
            {item.description && (
              <Section id="overview" title={t.community.overview}>
                <SafeMarkdown source={item.description} />
              </Section>
            )}
            <Section id="graph" title={t.workflows.graphTitle} count={item.node_count}>
              {item.graph && item.graph.nodes.length > 0 ? (
                <div className="grid gap-3">
                  <WorkflowGraphView graph={item.graph} label={`${t.workflows.graphTitle}: ${item.title}`} codeLabel={t.workflows.codeNode} />
                  <p className="m-0 text-xs text-muted-foreground">{t.workflows.graphNote}</p>
                </div>
              ) : (
                <p className="m-0 text-sm text-muted-foreground">{t.workflows.noGraph}</p>
              )}
            </Section>
            {versions.ok && versions.data.items.length > 0 && (
              <Section id="versions" title={t.community.versionsTitle} count={versions.data.items.length}>
                <VersionList locale={locale} versions={versions.data.items} />
              </Section>
            )}
          </>
        }
        aside={
          <>
            <SideCard title={t.workflows.importTitle}>
              <Steps steps={t.workflows.importSteps} />
              <p className="mt-5 mb-0 text-xs leading-5 text-muted-foreground">{t.workflows.importNote}</p>
              <p className="mt-3 mb-0 flex flex-wrap gap-x-1.5 text-xs text-muted-foreground">
                {t.community.noApp}
                <a className="font-semibold text-primary hover:underline" href={localePath(locale, "/docs/start/download")}>
                  {t.community.getApp}
                </a>
              </p>
            </SideCard>
            <SideCard title={t.community.downloadTrend}>
              <Sparkline locale={locale} points={item.downloads_30d ?? []} label={t.community.downloadTrend} />
            </SideCard>
            <SideCard title={t.community.info}>
              <InfoList
                rows={[
                  { label: t.community.version, value: <span className="font-mono">{versionLabel(item.version)}</span> },
                  { label: t.workflows.graphTitle, value: `${item.node_count} ${t.workflows.nodes}` },
                  { label: t.community.download, value: <span className="tabular-nums">{formatCount(item.downloads, locale)}</span> },
                  { label: t.community.published, value: formatDate(item.created_at, locale) },
                  { label: t.community.updated, value: formatDate(item.updated_at, locale) },
                ]}
              />
              {item.tags.length > 0 && (
                <div className="mt-4 border-t border-border pt-4">
                  <TagLinks locale={locale} section="/workflows" tags={item.tags} />
                </div>
              )}
            </SideCard>
            <div className="flex flex-wrap items-center justify-between gap-2 px-1">
              <Link className="text-sm font-semibold text-primary hover:underline" href={localePath(locale, "/docs/guides/workflows")}>
                {t.workflows.guideLink}
              </Link>
              <ReportButton locale={locale} kind="workflow" slug={item.slug} />
            </div>
          </>
        }
      />
      {more.length > 0 && (
        <section className="border-t border-border bg-secondary/30">
          <div className="mx-auto max-w-[76rem] px-5 py-12 sm:px-8">
            <h2 className="mt-0 mb-6 text-lg font-semibold tracking-tight">{t.workflows.more}</h2>
            <ul className="m-0 grid list-none gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3">
              {more.map((other) => (
                <li key={other.slug} className="grid">
                  <WorkflowCard locale={locale} item={other} />
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}
    </>
  );
}
