import type { Metadata } from "next";
import { Suspense } from "react";
import { notFound } from "next/navigation";

import { CommunityHeader } from "@/components/community/community-header";
import { ShareListSkeleton } from "@/components/community/share-skeleton";
import { ShareBrowser } from "@/components/community/shares";
import { cookieHeader, loadShareList } from "@/components/community/share-server";
import type { ShareListQuery } from "@/components/community/share-utils";
import { isLocale, localePath, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { listPlugins, listWorkflows } from "@/lib/registry";
import { pageMetadata } from "@/lib/seo";
import { CloudApiError } from "@/lib/cloud";

type Params = Promise<{ locale: string }>;
type SearchParams = Promise<{ q?: string | string[]; kind?: string | string[]; sort?: string | string[] }>;

/** 查询串里的值可能是数组;社区只认第一个。 */
function first(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

function normalizeQuery(params: Awaited<SearchParams>): ShareListQuery {
  const kind = first(params.kind);
  return {
    q: first(params.q).trim().slice(0, 200),
    kind: kind === "workflow" || kind === "board" ? kind : "",
    sort: first(params.sort) === "hot" ? "hot" : "new",
  };
}

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

/**
 * 列表页的取数部分,单独放在 Suspense 里。
 *
 * 页面骨架(标题、标签页、站头站尾)先出去,**分享内容随后流式补上** —— 首屏不必等云端,
 * 而搜到这一页的爬虫最终拿到的 HTML 里仍然有真实标题和摘要。
 */
async function ShareListSection({ locale, query }: { locale: Locale; query: ShareListQuery }) {
  const cookie = await cookieHeader();
  const t = getMessages(locale).community;
  let page: Awaited<ReturnType<typeof loadShareList>> | null = null;
  let message = "";
  try {
    page = await loadShareList(query, cookie);
  } catch (error) {
    message = error instanceof CloudApiError ? error.text(locale) : t.loadFailed;
  }
  return <ShareBrowser locale={locale} initial={page} initialError={message} initialQuery={query} />;
}

export const dynamic = "force-dynamic";

export default async function CommunityPage({ params, searchParams }: { params: Params; searchParams: SearchParams }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const query = normalizeQuery(await searchParams);
  const t = getMessages(locale).community;

  return (
    <>
      <CommunityHeader
        locale={locale}
        active="shares"
        counts={{ plugins: listPlugins(locale).length, workflows: listWorkflows(locale).length }}
        title={t.sharesTitle}
        lede={t.sharesLede}
        contribute={{ label: t.uploadCta, href: localePath(locale, "/community/upload") }}
      />
      <section className="bg-paper">
        <div className="mx-auto max-w-[76rem] px-5 py-10 sm:px-8 sm:pb-24">
          <Suspense fallback={<ShareListSkeleton locale={locale} />}>
            <ShareListSection locale={locale} query={query} />
          </Suspense>
        </div>
      </section>
    </>
  );
}
