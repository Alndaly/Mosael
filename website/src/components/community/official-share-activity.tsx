"use client";

import { useQuery } from "@tanstack/react-query";

import { getMessages } from "@/i18n/messages";
import { CloudApiError, cloudShares, type CloudShare, type CloudShareKind } from "@/lib/cloud";
import { useMyShares, useViewer } from "@/lib/queries";
import { queryKeys } from "@/lib/queryKeys";
import { SITE } from "@/lib/site";
import type { Locale } from "@/i18n/config";

import { CommentSection, ShareCommentCountProvider, ShareEngagement } from "./share-detail";
import { publicIdentity } from "./share-utils";

/**
 * 官方静态详情页（/workflows、/plugins）里的互动岛。
 *
 * 官方内容在 Cloud 也有一条带 slug 的 share；静态页保留它自己的目录 / 步骤 / 文档，
 * 互动（点赞、收藏、评论、统计）则按 slug 对回那条 share。这样官方详情只有一张脸，
 * 但点赞收藏不会在「收敛到静态页」时消失。
 */

type ActivityProps = {
  locale: Locale;
  slug: string;
  kind: Extract<CloudShareKind, "workflow" | "plugin">;
};

function useOfficialShare({ locale, slug, kind }: ActivityProps): { share: CloudShare | null; loading: boolean } {
  const query = useMyShares(SITE.officialHandle);
  const shareLocale = locale === "zh" ? "zh-CN" : "en-US";
  const share =
    query.data?.find(
      (item) => item.slug === slug && item.kind === kind && item.locale === shareLocale,
    ) ?? null;
  return { share, loading: query.isPending };
}

function failureText(locale: Locale, failure: unknown): string {
  return failure instanceof CloudApiError ? failure.text(locale) : getMessages(locale).community.loadFailed;
}

/** 页头互动：点赞 / 收藏 + 下载、点赞、收藏、评论四项统计。下载与打开仍在页头主按钮。 */
export function OfficialShareEngagement(props: ActivityProps) {
  const { share, loading } = useOfficialShare(props);
  const viewer = useViewer().data;

  if (loading) {
    return <div className="h-[5.5rem] w-full animate-pulse rounded-2xl bg-secondary/60 lg:w-[24rem]" aria-hidden />;
  }
  if (!share) return null;

  return (
    <ShareCommentCountProvider initialCount={share.stats.comments}>
      <ShareEngagement
        locale={props.locale}
        share={share}
        signedIn={Boolean(viewer)}
        showShareActions={false}
      />
    </ShareCommentCountProvider>
  );
}

/** 正文底部评论区。评论仍写在那条官方 share 上，和从旧分享地址进来时是同一组数据。 */
export function OfficialShareComments(props: ActivityProps) {
  const { share, loading } = useOfficialShare(props);
  const viewerQuery = useViewer();
  const commentsQuery = useQuery({
    queryKey: queryKeys.shareComments(share?.id ?? ""),
    queryFn: () => cloudShares.comments(share!.id, { limit: 30 }),
    enabled: Boolean(share),
  });

  if (loading || viewerQuery.isPending) {
    return <div className="h-24 animate-pulse rounded-2xl bg-secondary/40" aria-hidden />;
  }
  if (!share) return null;
  if (commentsQuery.isPending) {
    return <div className="h-24 animate-pulse rounded-2xl bg-secondary/40" aria-hidden />;
  }

  return (
    <CommentSection
      key={share.id}
      locale={props.locale}
      shareId={share.id}
      initial={commentsQuery.data ?? null}
      initialError={commentsQuery.error ? failureText(props.locale, commentsQuery.error) : ""}
      viewer={viewerQuery.data ? publicIdentity(viewerQuery.data) : null}
    />
  );
}
