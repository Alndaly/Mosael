"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowUpRight,
  Bookmark,
  Download,
  LoaderCircle,
  MessageSquare,
  ThumbsUp,
} from "lucide-react";
import * as React from "react";

import { actionClass } from "@/components/community/detail";
import { IdentityForm } from "@/components/community/identity-form";
import { InitialTile } from "@/components/community/tile";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import {
  CloudApiError,
  cloudShares,
  type CloudComment,
  type CloudCommentPage,
  type CloudIdentity,
  type CloudShare,
} from "@/lib/cloud";
import { invalidateAfterShareInteract } from "@/lib/query-invalidation";
import { cn } from "@/lib/utils";

import { communityLoginHref, formatShareDate, shareFilename } from "./share-utils";

function errorText(locale: Locale, failure: unknown, fallback: string): string {
  return failure instanceof CloudApiError ? failure.text(locale) : fallback;
}

function authorName(author: CloudIdentity): string {
  return author.display_name?.trim() || author.handle || "—";
}

/**
 * 详情页里两个 client island(右上角统计卡 / 正文评论区)共用的评论数。
 *
 * 旧实现靠 window 自定义事件在两个 island 之间广播评论数:那是一条绕过查询缓存的全局
 * 旁路,谁都能发、谁都能收,列表页面还收不到。现在评论数只活在**这一页的 React state**
 * 里,由这个 provider 把两个 island 包在一起;「别的页面要跟着变」交给
 * `invalidateAfterShareInteract(queryClient, "comment")`。
 *
 * 初始值取服务端渲染时那份 `share.stats.comments`,点完评论 / 删除后本地乐观地加减,
 * 立刻反映在统计卡上。
 */
type CommentCountState = { count: number; adjust: (delta: number) => void };

const CommentCountContext = React.createContext<CommentCountState | null>(null);

export function ShareCommentCountProvider({
  initialCount,
  children,
}: {
  initialCount: number;
  children: React.ReactNode;
}) {
  const [count, setCount] = React.useState(initialCount);
  const adjust = React.useCallback((delta: number) => {
    setCount((value) => Math.max(0, value + delta));
  }, []);
  const value = React.useMemo(() => ({ count, adjust }), [count, adjust]);
  return <CommentCountContext.Provider value={value}>{children}</CommentCountContext.Provider>;
}

function StatCell({ label, value }: { label: string; value: number }) {
  return (
    <div className="grid gap-0.5">
      <dt className="m-0 text-[11px] text-muted-foreground">{label}</dt>
      <dd className="m-0 font-mono text-sm font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

/**
 * 详情页右上角那一簇:深链、下载、点赞、收藏,外加四项统计。
 *
 * - 深链只生成 `mosael://import?share=<id>`,桌面端那笔(③)接住它,这里不实现客户端;
 * - 下载走 `POST /shares/{id}/download`(顺带 downloads +1),再落成 `<标题 slug>.json`;
 * - 未登录点按钮**不静默失败**:给出「登录后才能…」和带回跳的登录链接。
 */
export function ShareEngagement({
  locale,
  share,
  signedIn,
}: {
  locale: Locale;
  share: CloudShare;
  signedIn: boolean;
}) {
  const t = getMessages(locale).community;
  const detailPath = localePath(locale, `/community/${share.id}`);
  const queryClient = useQueryClient();
  // provider 在详情页外层(见 page.tsx);万一单独用这个组件,退回服务端给的那份数。
  const sharedCommentCount = React.useContext(CommentCountContext);
  const [liked, setLiked] = React.useState(share.liked_by_me);
  const [favorited, setFavorited] = React.useState(share.favorited_by_me);
  const [likes, setLikes] = React.useState(share.stats.likes);
  const [favorites, setFavorites] = React.useState(share.stats.favorites);
  const [downloads, setDownloads] = React.useState(share.stats.downloads);
  const [busyLike, setBusyLike] = React.useState(false);
  const [busyFavorite, setBusyFavorite] = React.useState(false);
  const [downloading, setDownloading] = React.useState(false);
  const [needsLogin, setNeedsLogin] = React.useState(false);
  const [error, setError] = React.useState("");

  const handleFailure = (failure: unknown, fallback: string) => {
    if (failure instanceof CloudApiError && failure.status === 401) {
      setNeedsLogin(true);
      return;
    }
    setError(errorText(locale, failure, fallback));
  };

  const toggleLike = async () => {
    if (!signedIn) {
      setNeedsLogin(true);
      return;
    }
    if (busyLike) return;
    setBusyLike(true);
    setError("");
    const next = !liked;
    try {
      await cloudShares.like(share.id, next);
      setLiked(next);
      setLikes((value) => Math.max(0, value + (next ? 1 : -1)));
      // 详情页的数字先本地变;列表卡片 / 我的分享靠标脏,回去时重取。
      void invalidateAfterShareInteract(queryClient, "like");
    } catch (failure) {
      handleFailure(failure, t.loadFailed);
    } finally {
      setBusyLike(false);
    }
  };

  const toggleFavorite = async () => {
    if (!signedIn) {
      setNeedsLogin(true);
      return;
    }
    if (busyFavorite) return;
    setBusyFavorite(true);
    setError("");
    const next = !favorited;
    try {
      await cloudShares.favorite(share.id, next);
      setFavorited(next);
      setFavorites((value) => Math.max(0, value + (next ? 1 : -1)));
      void invalidateAfterShareInteract(queryClient, "favorite");
    } catch (failure) {
      handleFailure(failure, t.loadFailed);
    } finally {
      setBusyFavorite(false);
    }
  };

  const download = async () => {
    if (downloading) return;
    setDownloading(true);
    setError("");
    try {
      const { payload } = await cloudShares.download(share.id);
      // 下载数在服务端 +1:列表卡片上的 downloads 要重取;详情页自己的数字先本地 +1。
      void invalidateAfterShareInteract(queryClient, "download");
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = shareFilename(share.title);
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      // 立刻 revoke 在部分浏览器里会让下载拿到空文件;等一拍再释放。
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setDownloads((value) => value + 1);
    } catch (failure) {
      handleFailure(failure, t.downloadFailed);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap gap-2.5">
        <a href={`mosael://import?share=${share.id}`} className={actionClass(true)}>
          <ArrowUpRight className="size-4" aria-hidden />
          {t.openInApp}
        </a>
        <button type="button" onClick={() => void download()} disabled={downloading} className={actionClass(false)}>
          {downloading ? (
            <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
          ) : (
            <Download className="size-4" aria-hidden />
          )}
          {downloading ? t.downloading : t.download}
        </button>
        <button
          type="button"
          onClick={() => void toggleLike()}
          aria-pressed={liked}
          title={liked ? t.liked : t.like}
          className={cn(
            actionClass(false),
            liked && "border-primary/50 bg-brand-soft text-primary",
          )}
        >
          <ThumbsUp className="size-4" aria-hidden />
          {liked ? t.liked : t.like}
          <span className="font-mono text-xs tabular-nums opacity-80">{likes}</span>
        </button>
        <button
          type="button"
          onClick={() => void toggleFavorite()}
          aria-pressed={favorited}
          title={favorited ? t.favorited : t.favorite}
          className={cn(
            actionClass(false),
            favorited && "border-primary/50 bg-brand-soft text-primary",
          )}
        >
          <Bookmark className="size-4" aria-hidden />
          {favorited ? t.favorited : t.favorite}
          <span className="font-mono text-xs tabular-nums opacity-80">{favorites}</span>
        </button>
      </div>

      <dl className="m-0 grid grid-cols-2 gap-2 rounded-2xl border border-border bg-card px-4 py-3 sm:grid-cols-4">
        <StatCell label={t.downloads} value={downloads} />
        <StatCell label={t.likes} value={likes} />
        <StatCell label={t.favorites} value={favorites} />
        <StatCell label={t.comments} value={sharedCommentCount?.count ?? share.stats.comments} />
      </dl>

      {needsLogin && (
        <output className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          {t.loginToInteract}
          <Link
            href={communityLoginHref(locale, detailPath)}
            className="font-semibold text-primary underline-offset-4 hover:underline"
          >
            {t.goLogin}
          </Link>
        </output>
      )}

      {error && (
        <p role="alert" className="m-0 flex items-start gap-1.5 rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-[13px] leading-5 text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * 评论区。读公开、写要登录 + 昵称。
 *
 * 没有昵称时后端回 409 `identity_required` —— 就地展开起名表单,保存后把刚才那条评论
 * 自动重发(用户不用再打一遍字)。未登录则给带回跳的登录链接,不把输入框藏起来装没这回事。
 */
export function CommentSection({
  locale,
  shareId,
  initial,
  initialError,
  viewer,
}: {
  locale: Locale;
  shareId: string;
  initial: CloudCommentPage | null;
  initialError: string;
  viewer: CloudIdentity | null;
}) {
  const t = getMessages(locale).community;
  const detailPath = localePath(locale, `/community/${shareId}`);
  const queryClient = useQueryClient();
  // 和右上角统计卡共用这一页的评论数(provider 在 page.tsx);单独用时退回不改数字。
  const sharedCommentCount = React.useContext(CommentCountContext);
  const [comments, setComments] = React.useState<CloudComment[]>(initial?.items ?? []);
  const [nextCursor, setNextCursor] = React.useState<string | null>(initial?.next_cursor ?? null);
  const [identity, setIdentity] = React.useState<CloudIdentity | null>(viewer);
  const [body, setBody] = React.useState("");
  const [error, setError] = React.useState(initialError);
  const [needsLogin, setNeedsLogin] = React.useState(false);
  const [needsIdentity, setNeedsIdentity] = React.useState(false);
  const [identityNotice, setIdentityNotice] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [pending, setPending] = React.useState<string | null>(null);
  const [retrying, setRetrying] = React.useState(false);

  const signedIn = identity !== null;
  const hasName = Boolean(identity?.display_name);

  const post = async (text: string) => {
    setBusy(true);
    setError("");
    try {
      const { comment } = await cloudShares.createComment(shareId, text);
      setComments((previous) => [comment, ...previous]);
      // 详情页的评论数先本地 +1;列表 / 我的分享 / 作者的通知靠标脏,回头重取。
      sharedCommentCount?.adjust(1);
      void invalidateAfterShareInteract(queryClient, "comment");
      setBody("");
      setPending(null);
    } catch (failure) {
      if (failure instanceof CloudApiError) {
        if (failure.status === 401) {
          setNeedsLogin(true);
        } else if (failure.code === "identity_required" || failure.status === 409) {
          setPending(text);
          setNeedsIdentity(true);
          // 后端那句中文就说清了「先起个名字」;照原样显示,别只留一个表单。
          setIdentityNotice(failure.text(locale));
        } else {
          setError(failure.text(locale));
        }
      } else {
        setError(t.commentFailed);
      }
    } finally {
      setBusy(false);
    }
  };

  const submitComment = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!signedIn) {
      setNeedsLogin(true);
      return;
    }
    if (busy) return;
    void post(body);
  };

  const retryComments = async () => {
    if (retrying) return;
    setRetrying(true);
    setError("");
    try {
      const page = await cloudShares.comments(shareId, { limit: 30 });
      setComments(page.items);
      setNextCursor(page.next_cursor);
    } catch (failure) {
      setError(errorText(locale, failure, t.loadFailed));
    } finally {
      setRetrying(false);
    }
  };

  const loadMore = async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    setError("");
    try {
      const page = await cloudShares.comments(shareId, { limit: 30, cursor: nextCursor });
      setComments((previous) => [...previous, ...page.items]);
      setNextCursor(page.next_cursor);
    } catch (failure) {
      setError(errorText(locale, failure, t.loadFailed));
    } finally {
      setLoadingMore(false);
    }
  };

  const deleteComment = async (commentId: string) => {
    setError("");
    try {
      await cloudShares.deleteComment(shareId, commentId);
      setComments((previous) => previous.filter((comment) => comment.id !== commentId));
      sharedCommentCount?.adjust(-1);
      void invalidateAfterShareInteract(queryClient, "comment");
    } catch (failure) {
      setError(errorText(locale, failure, t.loadFailed));
    }
  };

  const onIdentityDone = (updated: CloudIdentity) => {
    setIdentity(updated);
    setNeedsIdentity(false);
    if (pending) {
      const text = pending;
      setBody(text);
      void post(text);
    }
  };

  const ownComment = (comment: CloudComment) =>
    Boolean(identity?.handle) && comment.author.handle === identity?.handle;

  return (
    <section id="comments" className="scroll-mt-28">
      <h2 className="mt-0 mb-5 flex items-center gap-2 border-b border-border pb-3 text-lg font-semibold tracking-tight">
        {t.commentsTitle}
        <span className="rounded-full bg-secondary px-2 py-0.5 font-mono text-xs tabular-nums text-muted-foreground">
          {comments.length}
        </span>
      </h2>

      <div className="grid gap-6">
        {!signedIn || needsLogin ? (
          <p className="m-0 flex flex-wrap items-center gap-2 rounded-2xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
            <MessageSquare className="size-4 shrink-0" aria-hidden />
            {t.commentLogin}
            <Link
              href={communityLoginHref(locale, detailPath)}
              className="font-semibold text-primary underline-offset-4 hover:underline"
            >
              {t.goLogin}
            </Link>
          </p>
        ) : !hasName || needsIdentity ? (
          <div className="grid gap-3 rounded-2xl border border-border bg-card p-5">
            {identityNotice && (
              <output className="block rounded-xl border border-primary/25 bg-brand-soft px-3 py-2 text-[13px] leading-5 text-primary">
                {identityNotice}
              </output>
            )}
            <IdentityForm locale={locale} initialDisplayName={identity?.display_name ?? ""} onDone={onIdentityDone} />
          </div>
        ) : (
          <form onSubmit={submitComment} className="grid gap-2.5">
            <label htmlFor="community-comment" className="sr-only">
              {t.commentPlaceholder}
            </label>
            <textarea
              id="community-comment"
              value={body}
              onChange={(event) => setBody(event.target.value)}
              placeholder={t.commentPlaceholder}
              rows={4}
              maxLength={2000}
              className="w-full resize-y rounded-2xl border border-input/80 bg-card px-4 py-3 text-[16px] leading-6 text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-3 focus-visible:ring-primary/20"
            />
            <div className="flex items-center justify-between gap-3">
              <span className="font-mono text-xs text-muted-foreground tabular-nums">{body.length} / 2000</span>
              <button type="submit" disabled={busy} className={actionClass(true)}>
                {busy ? <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
                {busy ? t.posting : t.postComment}
              </button>
            </div>
          </form>
        )}

        {error && (
          <div
            role="alert"
            className="flex flex-wrap items-center gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
          >
            <AlertCircle className="size-4 shrink-0" aria-hidden />
            <span className="min-w-0 flex-1">{error}</span>
            {initial === null && (
              <button
                type="button"
                onClick={() => void retryComments()}
                disabled={retrying}
                className="rounded-full border border-destructive/40 px-3 py-1.5 font-semibold hover:bg-destructive/10 disabled:opacity-60"
              >
                {t.retry}
              </button>
            )}
          </div>
        )}

        {comments.length > 0 ? (
          <ul className="m-0 grid list-none gap-4 p-0">
            {comments.map((comment) => (
              <li key={comment.id} className="flex min-w-0 items-start gap-3 rounded-2xl border border-border bg-card p-4">
                <InitialTile
                  seed={comment.author.avatar_seed || comment.author.handle || comment.id}
                  name={authorName(comment.author)}
                  size="sm"
                />
                <div className="grid min-w-0 flex-1 gap-1">
                  <p className="m-0 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                    <span className="font-semibold text-foreground">{authorName(comment.author)}</span>
                    <span aria-hidden>·</span>
                    <time dateTime={comment.created_at}>{formatShareDate(comment.created_at, locale)}</time>
                    {ownComment(comment) && (
                      <button
                        type="button"
                        onClick={() => void deleteComment(comment.id)}
                        className="ml-auto text-xs text-muted-foreground underline-offset-4 hover:text-destructive hover:underline"
                      >
                        {t.deleteComment}
                      </button>
                    )}
                  </p>
                  <p className="m-0 text-sm leading-6 whitespace-pre-wrap [overflow-wrap:anywhere]">{comment.body}</p>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          !error && <p className="m-0 text-sm text-muted-foreground">{t.noComments}</p>
        )}

        {nextCursor && (
          <div className="flex justify-center">
            <button
              type="button"
              onClick={() => void loadMore()}
              disabled={loadingMore}
              className="inline-flex min-h-10 items-center gap-2 rounded-full border border-border bg-card px-4 text-sm font-semibold transition-colors hover:border-primary/50 hover:text-primary disabled:opacity-60"
            >
              {loadingMore ? (
                <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
              ) : null}
              {loadingMore ? t.loadingMore : t.loadMoreComments}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
