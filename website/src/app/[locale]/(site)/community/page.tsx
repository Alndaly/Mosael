import type { Metadata } from "next";
import { Suspense } from "react";
import { notFound } from "next/navigation";

import { CommunityHeader } from "@/components/community/community-header";
import { ShareListSkeleton } from "@/components/community/share-skeleton";
import { ShareBrowser } from "@/components/community/shares";
import { cookieHeader, loadShareList } from "@/components/community/share-server";
import { parseShareQuery, uploadCtaSurface } from "@/components/community/share-utils";
import { isLocale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { listPlugins, listWorkflows } from "@/lib/registry";
import { pageMetadata } from "@/lib/seo";
import { CloudApiError, type CloudSharePage } from "@/lib/cloud";

type Params = Promise<{ locale: string }>;
type SearchParams = Promise<{ q?: string | string[]; kind?: string | string[]; sort?: string | string[] }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).community;
  return pageMetadata({
    locale,
    path: "/community",
    title: t.sharesSeoTitle,
    description: t.sharesSeoDescription,
    keywords: t.sharesKeywords,
  });
}

export const dynamic = "force-dynamic";

/**
 * 社区列表页。
 *
 * 首屏这一份取数同时回答三件事:列表内容、页头 tab 上的分享数(拿得到时)、以及
 * 「去上传」该归页头还是归空态。所以在这里 await 一次,再把同一份结果交给列表组件 ——
 * 云端只问一遍。
 *
 * 取舍:页头因此要等这一次取数才出(以前是先出壳、内容随后流)。换来的是一条明确的规则:
 * 列表为空时页头不给 CTA,空态给;列表非空时页头给,空态根本不存在。列表区仍包在
 * Suspense 里 —— 换筛选 / 翻页时的骨架由列表组件自己出,边界在这里不会被挂起。
 */
export default async function CommunityPage({ params, searchParams }: { params: Params; searchParams: SearchParams }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = getMessages(locale).community;
  // 首屏和地址栏共用同一套解析(share-utils),刷新 / 分享出去的链接结果一致。
  const query = parseShareQuery(await searchParams);
  const cookie = await cookieHeader();

  let page: CloudSharePage | null = null;
  let message = "";
  try {
    page = await loadShareList(query, cookie);
  } catch (error) {
    message = error instanceof CloudApiError ? error.text(locale) : t.loadFailed;
  }

  const hasShares = (page?.items.length ?? 0) > 0;
  return (
    <>
      <CommunityHeader
        locale={locale}
        counts={{
          plugins: listPlugins(locale).length,
          workflows: listWorkflows(locale).length,
        }}
        title={t.sharesTitle}
        lede={t.sharesLede}
        // 「去上传」只出现一次:列表非空归页头,空了交给空态(见 uploadCtaSurface)。
        contribute={
          uploadCtaSurface(hasShares) === "header"
            ? { label: t.uploadCta, href: localePath(locale, "/community/upload") }
            : null
        }
      />
      <section className="bg-paper">
        <div className="mx-auto max-w-[76rem] px-5 py-10 sm:px-8 sm:pb-24">
          <Suspense fallback={<ShareListSkeleton locale={locale} />}>
            <ShareBrowser locale={locale} initial={page} initialError={message} initialQuery={query} />
          </Suspense>
        </div>
      </section>
    </>
  );
}
