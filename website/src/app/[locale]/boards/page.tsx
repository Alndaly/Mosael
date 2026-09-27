import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";

import { BoardList } from "@/components/community/board-list";
import { CommunityHeader, HeaderAction } from "@/components/community/community-header";
import { CommunityDown, CommunityUnavailable } from "@/components/community/shell";
import { isLocale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { REQUESTED } from "@/lib/community/endpoints";
import { communityEnabled, serverGet } from "@/lib/community/server";
import type { Page, ShareSummary } from "@/lib/community/types";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).boards;
  return { title: `${t.title} · Mosael`, description: t.lede };
}

/** 公开(`public`)的分享画板。`unlisted` 的只有知道链接的人能看,不在这里列。 */
export default async function BoardsPage({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  await connection();
  if (!communityEnabled()) return <CommunityUnavailable locale={locale} />;
  const t = getMessages(locale);
  const result = await serverGet<Page<ShareSummary>>(REQUESTED.publicShares({ limit: 24 }), locale);
  return (
    <>
      <CommunityHeader
        locale={locale}
        active="boards"
        title={t.boards.title}
        lede={t.boards.lede}
        actions={
          <HeaderAction href={localePath(locale, "/docs/start/download")} primary>
            {t.boards.getApp}
          </HeaderAction>
        }
      />
      <section className="bg-paper">
        <div className="mx-auto max-w-[76rem] px-5 py-10 sm:px-8 sm:pb-24">
          {result.ok ? <BoardList locale={locale} initial={result.data} /> : <CommunityDown locale={locale} />}
        </div>
      </section>
    </>
  );
}
