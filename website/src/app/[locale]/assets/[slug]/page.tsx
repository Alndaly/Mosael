import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { AlertTriangle, Box } from "lucide-react";

import { ASSET_KIND_ICON, AssetCard, versionLabel } from "@/components/community/cards";
import { Sparkline } from "@/components/community/charts";
import { DetailBody, DetailHeader, InfoList, Section, SideCard, Steps, TagLinks, VersionList } from "@/components/community/detail";
import { LikeButton, ReportButton } from "@/components/community/item-actions";
import { SafeMarkdown } from "@/components/community/safe-markdown";
import { CommunityDown, CommunityUnavailable, PageShell } from "@/components/community/shell";
import { isLocale, localePath, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { ENDPOINTS } from "@/lib/community/endpoints";
import { formatCount, formatDate } from "@/lib/community/format";
import { communityEnabled, serverGet } from "@/lib/community/server";
import { toPlainText } from "@/lib/inline-markdown";
import type { AssetDetail, AssetReference, AssetSummary, ItemVersion, Page } from "@/lib/community/types";

type Props = { params: Promise<{ locale: string; slug: string }> };

async function load(locale: Locale, slug: string) {
  return serverGet<AssetDetail>(ENDPOINTS.items.detail("asset", slug), locale);
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!isLocale(locale) || !communityEnabled()) return {};
  const result = await load(locale, slug);
  if (!result.ok) return {};
  const cover = result.data.cover_url;
  return {
    title: `${result.data.title} · ${getMessages(locale).assets.title}`,
    description: toPlainText(result.data.summary),
    ...(cover ? { openGraph: { images: [cover] } } : {}),
  };
}

/**
 * 参考图墙:一张一格,角标写角度(正面、三视图……)。**图是用户上传的**:只作为 `<img>` 显示,
 * 地址来自社区服务(按内容哈希存,见 ADR 0026 §6),不拼进任何别的地方。
 */
function ReferenceWall({
  locale,
  references,
  media,
  cover,
}: {
  locale: Locale;
  references: AssetReference[];
  media: AssetDetail["media"];
  cover?: string;
}) {
  const t = getMessages(locale).assets;
  return (
    <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-3 p-0">
      {references.map((reference) => {
        const url = media?.[reference.sha256]?.url;
        const role = t.roles[reference.role as keyof typeof t.roles] ?? reference.role;
        return (
          <li key={reference.sha256} className="relative overflow-hidden rounded-xl border border-border bg-secondary/50">
            {/* 图绝对定位铺满这一格:放在 grid 里用 size-full 的话,横图(三视图)的高度算不出来,只铺满上半格。 */}
            <div className="relative grid aspect-square place-items-center">
              {url ? (
                // oxlint-disable-next-line nextjs/no-img-element
                <img src={url} alt={role} loading="lazy" className="absolute inset-0 size-full object-cover" />
              ) : (
                <Box className="size-6 text-muted-foreground" aria-hidden />
              )}
            </div>
            <span className="absolute bottom-2 left-2 rounded-full bg-background/85 px-2 py-0.5 text-xs font-medium backdrop-blur">
              {role}
              {reference.sha256 === cover && " · ★"}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export default async function AssetDetailPage({ params }: Props) {
  const { locale, slug } = await params;
  if (!isLocale(locale)) notFound();
  await connection();
  if (!communityEnabled()) return <CommunityUnavailable locale={locale} />;
  const t = getMessages(locale);
  const result = await load(locale, slug);
  if (!result.ok) {
    if (result.error.status === 404 || result.error.status === 410) notFound();
    return (
      <PageShell eyebrow={t.community.name} title={t.assets.title}>
        <CommunityDown locale={locale} message={result.error.message} />
      </PageShell>
    );
  }
  const asset = result.data;
  const bundle = asset.bundle;
  const [versions, similar] = await Promise.all([
    serverGet<Page<ItemVersion>>(ENDPOINTS.items.versions("asset", slug), locale),
    serverGet<Page<AssetSummary>>(ENDPOINTS.items.list("asset", { author: asset.author.handle, sort: "downloads", limit: 4 }), locale),
  ]);
  const more = similar.ok ? similar.data.items.filter((other) => other.slug !== asset.slug).slice(0, 3) : [];
  const KindIcon = ASSET_KIND_ICON[asset.asset_kind] ?? Box;
  const variants = bundle?.variants ?? [];
  const timeOfDay = bundle?.attributes?.time_of_day;

  return (
    <>
      <DetailHeader
        locale={locale}
        section={{ label: t.assets.title, href: "/assets" }}
        tile={
          <span className="grid size-20 place-items-center overflow-hidden rounded-2xl border border-border bg-secondary/60">
            {asset.cover_url ? (
              // oxlint-disable-next-line nextjs/no-img-element
              <img src={asset.cover_url} alt="" className="size-full object-cover" />
            ) : (
              <KindIcon className="size-8 text-muted-foreground" aria-hidden />
            )}
          </span>
        }
        name={asset.title}
        author={asset.author}
        official={asset.official}
        version={versionLabel(asset.version)}
        summary={asset.summary}
        actions={
          <>
            <LikeButton locale={locale} kind="asset" slug={asset.slug} likes={asset.likes} />
            <ReportButton locale={locale} kind="asset" slug={asset.slug} />
          </>
        }
        notice={
          asset.real_person ? (
            <p
              role="note"
              className="m-0 flex max-w-[46rem] items-start gap-2.5 rounded-xl border border-[color:var(--tile-4)]/40 bg-[color-mix(in_oklab,var(--tile-4)_10%,var(--card))] px-3.5 py-3 text-sm leading-6"
            >
              <AlertTriangle className="mt-1 size-4 shrink-0 text-[color:var(--tile-4)]" aria-hidden />
              <span>
                <strong className="font-semibold">{t.assets.realPerson}</strong>
                {" · "}
                {t.assets.realPersonNote}
              </span>
            </p>
          ) : undefined
        }
      />
      <DetailBody
        main={
          <>
            <Section id="references" title={t.assets.referencesTitle} count={bundle?.references.length || undefined}>
              {bundle ? (
                <ReferenceWall locale={locale} references={bundle.references} media={asset.media} cover={bundle.cover_sha256} />
              ) : (
                <p className="m-0 text-muted-foreground">{t.assets.noDescription}</p>
              )}
            </Section>

            {bundle?.prompt && (
              <Section id="prompt" title={t.assets.prompt}>
                <p className="m-0 mb-3 text-sm leading-6 text-muted-foreground">{t.assets.promptNote}</p>
                <pre className="m-0 overflow-x-auto rounded-xl border border-border bg-card px-4 py-3 font-mono text-sm leading-6 whitespace-pre-wrap">
                  {bundle.prompt}
                </pre>
              </Section>
            )}

            {variants.length > 0 && (
              <Section id="variants" title={t.assets.variants} count={variants.length}>
                <p className="m-0 mb-4 text-sm leading-6 text-muted-foreground">{t.assets.variantsNote}</p>
                <div className="grid gap-6">
                  {variants.map((variant) => (
                    <div key={variant.name} className="grid gap-3">
                      <h3 className="m-0 text-base font-semibold">{variant.name}</h3>
                      {variant.prompt && <p className="m-0 font-mono text-xs leading-5 text-muted-foreground">{variant.prompt}</p>}
                      <ReferenceWall locale={locale} references={variant.references} media={asset.media} cover={variant.cover_sha256} />
                    </div>
                  ))}
                </div>
              </Section>
            )}

            <Section id="overview" title={t.community.overview}>
              {asset.description ? (
                // 作者写的说明:只经 SafeMarkdown,不进 MDX。
                <SafeMarkdown source={asset.description} />
              ) : (
                <p className="m-0 text-muted-foreground">{t.assets.noDescription}</p>
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
            <SideCard title={t.assets.importTitle}>
              <Steps steps={t.assets.importSteps} />
              <p className="mt-4 mb-0 text-xs leading-5 text-muted-foreground">{t.assets.importNote}</p>
              <p className="mt-5 mb-0 flex flex-wrap gap-x-1.5 text-xs text-muted-foreground">
                {t.community.noApp}
                <a className="font-semibold text-primary hover:underline" href={localePath(locale, "/docs/start/download")}>
                  {t.community.getApp}
                </a>
              </p>
            </SideCard>

            <SideCard title={t.community.downloadTrend}>
              <Sparkline locale={locale} points={asset.downloads_30d ?? []} label={t.community.downloadTrend} />
            </SideCard>

            <SideCard title={t.community.info}>
              <InfoList
                rows={[
                  { label: t.community.type, value: t.assets.kinds[asset.asset_kind] ?? asset.asset_kind },
                  { label: t.assets.referencesTitle, value: <span className="tabular-nums">{asset.reference_count}</span> },
                  ...(timeOfDay ? [{ label: t.assets.timeOfDay, value: timeOfDay }] : []),
                  { label: t.community.version, value: <span className="font-mono">{versionLabel(asset.version)}</span> },
                  { label: t.community.download, value: <span className="tabular-nums">{formatCount(asset.downloads, locale)}</span> },
                  { label: t.community.updated, value: formatDate(asset.updated_at, locale) },
                ]}
              />
              {asset.tags.length > 0 && (
                <div className="mt-4 border-t border-border pt-4">
                  <TagLinks locale={locale} section="/assets" tags={asset.tags} />
                </div>
              )}
            </SideCard>
          </>
        }
      />
      {more.length > 0 && (
        <section className="border-t border-border bg-secondary/30">
          <div className="mx-auto max-w-[76rem] px-5 py-12 sm:px-8">
            <h2 className="mt-0 mb-6 text-lg font-semibold tracking-tight">{t.assets.more}</h2>
            <ul className="m-0 grid list-none gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3">
              {more.map((other) => (
                <li key={other.slug} className="grid">
                  <AssetCard locale={locale} item={other} />
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}
    </>
  );
}
