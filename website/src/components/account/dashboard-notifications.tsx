"use client";

import { AlertCircle, Bell, LoaderCircle, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { formatShareDate } from "@/components/community/share-utils";
import { InitialTile } from "@/components/community/tile";
import { Button } from "@/components/ui/button";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages, type Messages } from "@/i18n/messages";
import { CloudApiError, cloudNotifications, type CloudIdentity, type CloudNotification } from "@/lib/cloud";
import { invalidateAfterMarkRead } from "@/lib/query-invalidation";
import { useNotifications } from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * 通知:**点赞 / 收藏 / 评论**三条来由,一条一行。
 *
 * 数据只来自 `GET /notifications`(经 `useNotifications` 走查询缓存:进分区不重拉、
 * 不轮询、不造假):公开身份只有 `display_name` / `handle` / `avatar_seed` 三列,
 * **没有 email**;`comment_preview` 是后端截好的**纯文本**,这里当文字渲染、不解析 markdown。
 *
 * 未读不只靠颜色:左边一个色点(**形状**)+ 整行加粗(**字重**)+ 读屏可读的「未读通知」。
 * 点一条会先标记这一条已读(`POST /notifications/read {ids:[id]}`),再去那条分享的详情。
 *
 * 头像和社区卡片 / 个人信息预览共用同一份 `InitialTile` 与 `--tile-*` 色相 —— 同一个
 * `avatar_seed` 在顶栏、社区、这里永远是同一块颜色,不在这一块再抄一份 `hueOf`。
 */

/** 通知一页的条数。后端默认 20,这里沿用。 */
export const NOTIFICATION_PAGE_SIZE = 20;

/** 通知里的「谁」:公开身份只有 display_name / handle,**没有邮箱可退**。 */
export function notificationName(actor: CloudIdentity): string {
  return actor.display_name?.trim() || actor.handle?.trim() || "—";
}

/** 头像色块的 seed:和社区卡片 / 个人信息预览同一优先级(avatar_seed → handle → 名字)。 */
export function notificationSeed(actor: CloudIdentity): string {
  return actor.avatar_seed?.trim() || actor.handle?.trim() || notificationName(actor);
}

/** 「做了什么」:三种 kind 各一句,文案全在 i18n 里。 */
export function notificationVerb(kind: CloudNotification["kind"], copy: Messages["dashboard"]): string {
  if (kind === "favorite") return copy.notificationFavorited;
  if (kind === "comment") return copy.notificationCommented;
  return copy.notificationLiked;
}

/** 点开一条通知要做的两件事。抽成参数是为了能在 node 测试里打桩真的跑一遍。 */
type OpenEffects = {
  markRead: (ids: string[]) => Promise<unknown>;
  navigate: (href: string) => void;
  href: string;
};

/**
 * 点开一条通知:未读的先标记已读,然后**立刻**去那条分享的详情。
 *
 * 标记已读是后台动作:失败不挡跳转、不弹错 —— 用户要看的是分享,不是那个小红点。
 */
export function openNotification(
  notification: Pick<CloudNotification, "id" | "read_at">,
  effects: OpenEffects,
): void {
  if (!notification.read_at) {
    try {
      void effects.markRead([notification.id]).catch(() => {});
    } catch {
      // 极端情况下同步抛错也不挡跳转。
    }
  }
  effects.navigate(effects.href);
}

export function DashboardNotifications({ locale, copy }: { locale: Locale; copy: Messages["dashboard"] }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const t = getMessages(locale).community;
  const loadFailed = copy.notificationsLoadFailed;

  // 列表走查询缓存(游标翻页用 infinite query):进分区不重拉、不轮询;标已读后由
  // `invalidateAfterMarkRead` 同时刷新站头角标与这里(**unread + 通知列表**)。
  const notifications = useNotifications(NOTIFICATION_PAGE_SIZE);
  const items = notifications.data?.pages.flatMap((page) => page.items) ?? [];
  // `unread` 是后端给的未读总数,取最后一页(每页都带同一个总数)。
  const unread = notifications.data?.pages.at(-1)?.unread ?? 0;
  // 首次进入没有缓存 → 骨架;失败后点重试也回到骨架(而不是让错误块留在屏幕上报旧错)。
  const loading = notifications.isPending || (notifications.isFetching && notifications.data === undefined);
  const loadingMore = notifications.isFetchingNextPage;
  const [marking, setMarking] = useState(false);
  // 写操作(标已读)的失败单独记;读列表的错误由 query 自己带。
  const [actionError, setActionError] = useState("");
  const queryError = notifications.isError
    ? notifications.error instanceof CloudApiError
      ? notifications.error.text(locale)
      : loadFailed
    : "";
  const error = actionError || queryError;

  /** 重试:让同一个查询再跑一次,不另写一套取数。 */
  const retry = () => {
    setActionError("");
    void notifications.refetch();
  };

  const loadMore = () => {
    if (!notifications.hasNextPage || notifications.isFetchingNextPage) return;
    setActionError("");
    void notifications.fetchNextPage();
  };

  const markAll = async () => {
    if (marking || unread === 0) return;
    setMarking(true);
    setActionError("");
    try {
      // 不传 ids = 全部标已读;传 [] 是「一条都不标」,别在这里传错。
      await cloudNotifications.markRead();
      // 清单:unread(站头角标)+ 通知列表 —— 一起失效,数字与行上的已读态才不会互相打架。
      await invalidateAfterMarkRead(queryClient);
    } catch (failure) {
      setActionError(failure instanceof CloudApiError ? failure.text(locale) : loadFailed);
    } finally {
      setMarking(false);
    }
  };

  const open = (notification: CloudNotification) => {
    openNotification(notification, {
      // 单条标已读也一样:刷 unread 与通知列表(跳转后站头角标也要跟着减)。
      markRead: async (ids) => {
        await cloudNotifications.markRead(ids);
        await invalidateAfterMarkRead(queryClient);
      },
      navigate: (href) => router.push(href),
      href: localePath(locale, `/community/${notification.share.id}`),
    });
  };

  if (loading) {
    return (
      <output className="block rounded-3xl border border-dashed border-border bg-card px-6 py-12 text-center text-sm leading-7 text-muted-foreground">
        {copy.notificationsLoading}
      </output>
    );
  }

  return (
    <div className="grid gap-4">
      {error && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1">{error}</span>
          <button
            type="button"
            onClick={retry}
            className="inline-flex items-center gap-1.5 rounded-full border border-destructive/40 px-3 py-1.5 font-semibold hover:bg-destructive/10"
          >
            <RotateCcw className="size-3.5" aria-hidden />
            {copy.retry}
          </button>
        </div>
      )}

      {items.length === 0 ? (
        !error && (
          <div className="rounded-3xl border border-dashed border-border bg-card px-6 py-16 text-center">
            <span className="inline-flex size-12 items-center justify-center rounded-2xl bg-secondary text-muted-foreground">
              <Bell className="size-5" aria-hidden />
            </span>
            <p className="mx-auto mt-4 mb-0 max-w-[34ch] text-sm leading-7 text-muted-foreground">
              {copy.notificationsEmpty}
            </p>
          </div>
        )
      ) : (
        <>
          {unread > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="m-0 inline-flex items-baseline gap-1.5 text-sm text-muted-foreground">
                <span className="font-mono text-foreground tabular-nums">{unread}</span>
                <span>{copy.notificationUnread}</span>
              </p>
              <Button
                variant="outline"
                disabled={marking}
                aria-busy={marking}
                onClick={() => void markAll()}
                className="min-h-9 rounded-full px-3.5 text-[13px] font-semibold"
              >
                {marking ? copy.markingRead : copy.markAllRead}
              </Button>
            </div>
          )}

          <ul className="m-0 grid list-none gap-2.5 p-0">
            {items.map((item) => {
              const isUnread = !item.read_at;
              const name = notificationName(item.actor);
              return (
                <li key={item.id} className="min-w-0">
                  <Link
                    href={localePath(locale, `/community/${item.share.id}`)}
                    onClick={(event) => {
                      // 带修饰键 / 中键的点击留给浏览器(新标签打开),不当普通点击劫持。
                      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                      event.preventDefault();
                      open(item);
                    }}
                    className={cn(
                      "group flex min-w-0 items-start gap-3 rounded-2xl border p-4 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                      isUnread
                        ? "border-primary/30 bg-primary/[0.04] hover:border-primary/50"
                        : "border-border bg-card hover:border-foreground/20",
                    )}
                  >
                    {/* 未读的第二通道:左边那颗色点。已读也占位,行首不跳。 */}
                    <span
                      aria-hidden
                      className={cn(
                        "mt-2 size-2 shrink-0 rounded-full",
                        isUnread ? "bg-primary" : "bg-transparent",
                      )}
                    />
                    <InitialTile seed={notificationSeed(item.actor)} name={name} size="sm" />
                    <div className="grid min-w-0 flex-1 gap-1">
                      <p
                        className={cn(
                          "m-0 text-sm leading-6 [overflow-wrap:anywhere]",
                          isUnread ? "font-semibold text-foreground" : "font-normal text-muted-foreground",
                        )}
                      >
                        <span className="text-foreground">{name}</span>
                        <span> {notificationVerb(item.kind, copy)} </span>
                        <span className="font-medium text-foreground">{item.share.title}</span>
                        {isUnread && <span className="sr-only"> · {copy.notificationUnread}</span>}
                      </p>
                      {/* 纯文本:评论里的 * / # 原样显示,不渲染 markdown。 */}
                      {item.kind === "comment" && item.comment_preview ? (
                        <p className="m-0 line-clamp-2 text-sm leading-6 text-muted-foreground">{item.comment_preview}</p>
                      ) : null}
                      <time dateTime={item.created_at} className="text-xs text-muted-foreground">
                        {formatShareDate(item.created_at, locale)}
                      </time>
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>

          {notifications.hasNextPage && (
            <div className="flex justify-center">
              <button
                type="button"
                onClick={() => void loadMore()}
                disabled={loadingMore}
                className="inline-flex min-h-11 items-center gap-2 rounded-full border border-border bg-card px-5 text-sm font-semibold transition-colors hover:border-primary/50 hover:text-primary disabled:opacity-60"
              >
                {loadingMore ? (
                  <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
                ) : null}
                {loadingMore ? t.loadingMore : t.loadMore}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
