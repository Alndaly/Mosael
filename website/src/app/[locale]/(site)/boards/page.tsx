import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { BoardBrowser } from "@/components/community/browse";
import { CommunityHeader } from "@/components/community/community-header";
import { isLocale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { listPlugins, listWorkflows } from "@/lib/registry";
import { pageMetadata } from "@/lib/seo";

type Params = Promise<{ locale: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).boards;
  return pageMetadata({ locale, path: "/boards", title: t.seoTitle, description: t.seoDescription, keywords: t.keywords });
}

/**
 * 画板列表(创意画板)。
 *
 * 和 `/plugins`、`/workflows` 同构:同一套页头 + 搜索 + 「去上传」,列表在浏览器里按
 * 当前语言取一次 —— 构建期不碰云端,所以仍是静态页。
 *
 * **整页只有 `kind=board`**:画布没有官方静态内容(registry 里只有插件 / 工作流),
 * 所以这里不混官方卡片,也不做「官方在前」的合并;一条都没有时给空态与上传入口。
 */
export default async function BoardsPage({ params }: { params: Params }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = getMessages(locale);

  return (
    <>
      <CommunityHeader
        locale={locale}
        counts={{ plugins: listPlugins(locale).length, workflows: listWorkflows(locale).length }}
        title={t.boards.heading}
        lede={t.boards.lede}
        // 页头**不给** CTA:这一页的列表是浏览器里取的,只有它知道此刻空不空。
        // 空态那条链接与非空时筛选区那颗按钮由列表自己出 —— 一屏永远只有一处「去上传」。
        contribute={null}
      />
      <section className="bg-paper">
        <div className="mx-auto max-w-[76rem] px-5 py-10 sm:px-8 sm:pb-24">
          <BoardBrowser locale={locale} />
        </div>
      </section>
    </>
  );
}
