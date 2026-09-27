import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { ArrowUpRight, Download, KeyRound, Shield } from "lucide-react";

import { PluginCard, versionLabel } from "@/components/community/cards";
import { Sparkline } from "@/components/community/charts";
import { ActionLink, DetailBody, DetailHeader, InfoList, Section, SideCard, Steps, TagLinks, VersionList } from "@/components/community/detail";
import { LikeButton, NewVersionLink, ReportButton } from "@/components/community/item-actions";
import { SafeMarkdown } from "@/components/community/safe-markdown";
import { CommunityDown, CommunityUnavailable, PageShell } from "@/components/community/shell";
import { PluginTile } from "@/components/community/tile";
import { isLocale, localePath, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { ENDPOINTS, browserUrl } from "@/lib/community/endpoints";
import { formatCount, formatDate } from "@/lib/community/format";
import { communityEnabled, serverGet } from "@/lib/community/server";
import { InlineMarkdown, toPlainText } from "@/lib/inline-markdown";
import type { ItemVersion, Page, PluginDetail, PluginSummary } from "@/lib/community/types";
import { SITE } from "@/lib/site";

type Props = { params: Promise<{ locale: string; slug: string }> };

async function load(locale: Locale, slug: string) {
  return serverGet<PluginDetail>(ENDPOINTS.items.detail("plugin", slug), locale);
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!isLocale(locale) || !communityEnabled()) return {};
  const result = await load(locale, slug);
  if (!result.ok) return {};
  return { title: `${result.data.title} · ${getMessages(locale).plugins.title}`, description: toPlainText(result.data.summary) };
}

/** `https?://` 以外的主页地址不进 `<a href>`:清单是作者写的。 */
function httpUrl(value: string | null | undefined): string {
  return typeof value === "string" && /^https?:\/\//.test(value) ? value : "";
}

export default async function PluginDetailPage({ params }: Props) {
  const { locale, slug } = await params;
  if (!isLocale(locale)) notFound();
  await connection();
  if (!communityEnabled()) return <CommunityUnavailable locale={locale} />;
  const t = getMessages(locale);
  const result = await load(locale, slug);
  if (!result.ok) {
    if (result.error.status === 404 || result.error.status === 410) notFound();
    return (
      <PageShell eyebrow={t.community.name} title={t.plugins.title}>
        <CommunityDown locale={locale} message={result.error.message} />
      </PageShell>
    );
  }
  const plugin = result.data;
  const [versions, similar] = await Promise.all([
    serverGet<Page<ItemVersion>>(ENDPOINTS.items.versions("plugin", slug), locale),
    serverGet<Page<PluginSummary>>(ENDPOINTS.items.list("plugin", { author: plugin.author.handle, sort: "downloads", limit: 4 }), locale),
  ]);
  const more = similar.ok ? similar.data.items.filter((other) => other.slug !== plugin.slug).slice(0, 3) : [];
  const official = plugin.official;
  const tools = plugin.extra?.tools ?? [];
  const credentials = plugin.extra?.credentials ?? [];
  const homepage = httpUrl(plugin.extra?.homepage);

  return (
    <>
      <DetailHeader
        locale={locale}
        section={{ label: t.plugins.title, href: "/plugins" }}
        tile={<PluginTile seed={plugin.plugin_id || plugin.slug} name={plugin.title} cover={plugin.cover_url} size="lg" />}
        name={plugin.title}
        author={plugin.author}
        official={plugin.official}
        version={versionLabel(plugin.version)}
        summary={plugin.summary}
        actions={
          <>
            {/* 深链只导航、不执行(electron/system/deepLink.ts):装过了就打开它的插件页,没装就
                打开市场、找到它 —— 装不装仍由人点,权限确认照旧弹。 */}
            <ActionLink href={`mosael://open?view=plugins&market=${encodeURIComponent(plugin.plugin_id)}`} primary>
              {t.community.openInApp}
            </ActionLink>
            <LikeButton locale={locale} kind="plugin" slug={plugin.slug} likes={plugin.likes} />
            <ActionLink href={browserUrl(ENDPOINTS.items.download("plugin", plugin.slug))}>
              <Download className="size-4" aria-hidden />
              {t.plugins.downloadZip}
            </ActionLink>
            <NewVersionLink locale={locale} kind="plugin" slug={plugin.slug} authorHandle={plugin.author.handle} />
          </>
        }
      />
      <DetailBody
        main={
          <>
            <Section id="overview" title={t.community.overview}>
              {plugin.description ? (
                // 作者写的说明(官方插件是它的 README):只经 SafeMarkdown,不进 MDX(见那个组件的说明)。
                <SafeMarkdown source={plugin.description} />
              ) : (
                <p className="m-0 text-muted-foreground">{t.plugins.noDoc}</p>
              )}
            </Section>

            <Section id="tools" title={t.plugins.toolsTitle} count={tools.length || undefined}>
              {tools.length === 0 ? (
                <p className="m-0 text-sm leading-7 text-muted-foreground">{t.plugins.toolsMcpNote}</p>
              ) : (
                <ul className="m-0 grid list-none gap-0 overflow-hidden rounded-2xl border border-border bg-card p-0">
                  {tools.map((tool) => (
                    <li key={tool.name} className="grid gap-1.5 border-border px-5 py-4 not-last:border-b">
                      <code className="w-fit rounded-md bg-secondary px-2 py-0.5 font-mono text-xs font-semibold">{tool.name}</code>
                      {tool.description && (
                        <p className="m-0 text-sm leading-6 text-muted-foreground">
                          <InlineMarkdown text={tool.description} />
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <Section id="permissions" title={t.plugins.permissionsTitle} count={plugin.permissions.length || undefined}>
              {plugin.permissions.length > 0 && (
                <div className="mb-4 flex flex-wrap gap-2">
                  {plugin.permissions.map((permission) => (
                    <span key={permission} className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 font-mono text-xs">
                      <Shield className="size-3.5 text-muted-foreground" aria-hidden />
                      {permission}
                    </span>
                  ))}
                </div>
              )}
              <p className="m-0 text-sm leading-7 text-muted-foreground">
                {plugin.permissions.length > 0 ? t.plugins.permissionsNote : t.plugins.noPermissionsNote}
              </p>
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
            <SideCard title={t.community.install}>
              {/* 官方的在应用默认的市场里;社区的在市场的「社区」来源下(ADR 0026 §4)。 */}
              <Steps steps={official ? t.plugins.officialSteps : t.plugins.communitySteps} />
              {!official && <p className="mt-4 mb-0 text-xs leading-5 text-muted-foreground">{t.plugins.communityNote}</p>}
              <p className="mt-5 mb-0 flex flex-wrap gap-x-1.5 text-xs text-muted-foreground">
                {t.community.noApp}
                <a className="font-semibold text-primary hover:underline" href={localePath(locale, "/docs/start/download")}>
                  {t.community.getApp}
                </a>
              </p>
            </SideCard>

            <SideCard title={t.community.downloadTrend}>
              <Sparkline locale={locale} points={plugin.downloads_30d ?? []} label={t.community.downloadTrend} />
            </SideCard>

            <SideCard title={t.community.info}>
              <InfoList
                rows={[
                  { label: t.community.version, value: <span className="font-mono">{versionLabel(plugin.version)}</span> },
                  { label: t.community.type, value: plugin.runtime === "mcp" ? t.plugins.kindMcp : t.plugins.kindScript },
                  { label: t.community.id, value: <code className="font-mono text-xs">{plugin.plugin_id}</code> },
                  { label: t.community.download, value: <span className="tabular-nums">{formatCount(plugin.downloads, locale)}</span> },
                  { label: t.community.updated, value: formatDate(plugin.updated_at, locale) },
                ]}
              />
              {plugin.tags.length > 0 && (
                <div className="mt-4 border-t border-border pt-4">
                  <TagLinks locale={locale} section="/plugins" tags={plugin.tags} />
                </div>
              )}
            </SideCard>

            <SideCard title={t.plugins.credentials}>
              {credentials.length > 0 ? (
                <ul className="m-0 grid list-none gap-2 p-0 text-sm">
                  {credentials.map((credential) => (
                    <li key={credential} className="flex items-center gap-2">
                      <KeyRound className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      {credential}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="m-0 text-sm text-muted-foreground">{t.plugins.noCredentials}</p>
              )}
            </SideCard>

            <div className="grid gap-2 px-1 text-sm font-semibold">
              {homepage && (
                <a className="inline-flex items-center gap-1 text-primary hover:underline" href={homepage} target="_blank" rel="noreferrer nofollow">
                  {t.plugins.homepage}
                  <ArrowUpRight className="size-3.5" aria-hidden />
                </a>
              )}
              <a className="inline-flex items-center gap-1 text-primary hover:underline" href={`${SITE.repo}/blob/main/docs/PLUGIN_MANIFEST.md`} target="_blank" rel="noreferrer">
                {t.plugins.manifestLink}
                <ArrowUpRight className="size-3.5" aria-hidden />
              </a>
              <span className="pt-1">
                <ReportButton locale={locale} kind="plugin" slug={plugin.slug} />
              </span>
            </div>
          </>
        }
      />
      {more.length > 0 && (
        <section className="border-t border-border bg-secondary/30">
          <div className="mx-auto max-w-[76rem] px-5 py-12 sm:px-8">
            <h2 className="mt-0 mb-6 text-lg font-semibold tracking-tight">{t.plugins.more}</h2>
            <ul className="m-0 grid list-none gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3">
              {more.map((other) => (
                <li key={other.slug} className="grid">
                  <PluginCard locale={locale} item={other} />
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}
    </>
  );
}
