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
import type { AssetSummary, Page } from "@/lib/community/types";

type Props = { params: Promise<{ locale: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> };

export async function generateMetadata({ params }: Pick<Props, "params">): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).assets;
  return { title: `${t.title} · Mosael`, description: t.lede };
}

/**
 * 社区的资产(人物 / 场景 / 道具,ADR 0027 §4)。请求时渲染,读社区服务。
 *
 * 没有「提交」按钮:资产是从应用里发的(参考图在应用的素材库里,分享包由应用做),官网只逛、只看。
 * 页头右上角是「怎么导入」的文档 —— 看中一个之后要做的那件事。
 */
export default async function AssetsPage({ params, searchParams }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  await connection();
  if (!communityEnabled()) return <CommunityUnavailable locale={locale} />;
  const t = getMessages(locale);
  const query = parseListQuery(await searchParams);
  const result = await serverGet<Page<AssetSummary>>(ENDPOINTS.items.list("asset", { ...query, limit: PAGE_SIZE }), locale);

  return (
    <>
      <CommunityHeader
        locale={locale}
        active="assets"
        title={t.assets.title}
        lede={t.assets.lede}
        actions={<HeaderAction href={localePath(locale, "/docs/guides/assets")}>{t.assets.importTitle}</HeaderAction>}
      />
      <section className="bg-paper">
        <div className="mx-auto max-w-[76rem] px-5 py-10 sm:px-8 sm:pb-24">
          {result.ok ? <ItemBrowser locale={locale} kind="asset" query={query} initial={result.data} /> : <CommunityDown locale={locale} />}
        </div>
      </section>
    </>
  );
}
