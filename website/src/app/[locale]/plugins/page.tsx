import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";

import { ItemBrowser } from "@/components/community/browse";
import { CommunityHeader, HeaderAction } from "@/components/community/community-header";
import { CommunityDown, CommunityUnavailable } from "@/components/community/shell";
import { isLocale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { ENDPOINTS, PAGE_SIZE, parseListQuery } from "@/lib/community/endpoints";
import { communityEnabled, serverGet } from "@/lib/community/server";
import type { Page, PluginSummary } from "@/lib/community/types";

type Props = { params: Promise<{ locale: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> };

export async function generateMetadata({ params }: Pick<Props, "params">): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).plugins;
  return { title: `${t.title} · Mosael`, description: t.lede };
}

/** 请求时渲染,读社区服务(ADR 0026 §8)。列表里只有审核通过的插件,官方的在 `official` 名下。 */
export default async function PluginsPage({ params, searchParams }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  await connection();
  if (!communityEnabled()) return <CommunityUnavailable locale={locale} />;
  const t = getMessages(locale);
  const query = parseListQuery(await searchParams);
  const result = await serverGet<Page<PluginSummary>>(ENDPOINTS.items.list("plugin", { ...query, limit: PAGE_SIZE }), locale);

  return (
    <>
      <CommunityHeader
        locale={locale}
        active="plugins"
        title={t.plugins.title}
        lede={t.plugins.lede}
        actions={
          <>
            <HeaderAction href={localePath(locale, "/docs/guides/writing-plugins")}>{t.plugins.writeGuide}</HeaderAction>
            <HeaderAction href={localePath(locale, "/plugins/new")} primary>
              {t.plugins.submit}
            </HeaderAction>
          </>
        }
      />
      <section className="bg-paper">
        <div className="mx-auto max-w-[76rem] px-5 py-10 sm:px-8 sm:pb-24">
          {result.ok ? (
            <ItemBrowser locale={locale} kind="plugin" query={query} initial={result.data} />
          ) : (
            <CommunityDown locale={locale} />
          )}
        </div>
      </section>
    </>
  );
}
