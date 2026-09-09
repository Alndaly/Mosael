import React from "react";
import { useQuery } from "@tanstack/react-query";
import { AtSign, LocateFixed, MapPin, MessageSquare } from "lucide-react";

import { listComments, listMembers, type CollaborationActor, type CollaborationComment } from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { CommentContent } from "@/features/boards/CommentCard";
import { relativeTime } from "@/lib/time";

/**
 * 一张画布上的讨论,集中读一遍。
 *
 * ## 为什么是右侧侧栏,不是居中对话框
 *
 * 这些讨论**说的就是背后那张画布**。此前它是一张 900×680 的居中对话框,打开的一瞬间把它要
 * 讲的东西整个盖住了 —— 读到「这里再收紧一点」时,"这里"已经看不见了。侧栏贴着右边,画布
 * 留在左边,"在画布中查看"跳过去之后视线不用重新找。
 *
 * ## 为什么不再分左右两栏
 *
 * 对话框那一版是「清单 + 详情」:左边一列摘要,右边一份全文。宽度 900px 时那是合理的;换到
 * 500px 的侧栏就摆不下,而且**在这个场景里它本来就是多余的** —— 摘要和全文的差别只是两行截断,
 * 为此要多点一下、多一份"当前选中"的状态,还让空态出现了两次(截图里左右各写了一遍
 * 「还没有评论」)。这里改成一条**流水**:每条讨论就是完整的一张卡,读下去即可。
 *
 * ## 它对 subject 是不认识的
 *
 * 画板和工作流是同一件事的两个 subject_type,后端的评论接口本来就是这么设计的。所以这里只收
 * `subjectType` / `subjectId`,不认识 Board 也不认识 Workflow —— 两个页面共用同一份,而不是
 * 各抄一份然后慢慢长歪。
 */
export type CollaborationSubject = "board" | "workflow";

function actorName(actor: CollaborationActor | null, fallback: string): string {
  return actor?.display_name || actor?.username || fallback;
}

/** 有坐标才跳得过去 —— 没有锚点的讨论(接口允许)不该给一个点了没反应的按钮。 */
function locatable(comment: CollaborationComment): boolean {
  return typeof comment.anchor?.x === "number" && typeof comment.anchor?.y === "number";
}

export function CollaborationSheet({
  open,
  onOpenChange,
  workspaceId,
  subjectType,
  subjectId,
  onJumpToComment,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string;
  subjectType: CollaborationSubject;
  subjectId: string;
  /** 跳到画布上那条讨论的原位。由调用方决定怎么跳(两个页面的视口 API 不一样)。 */
  onJumpToComment: (comment: CollaborationComment) => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const comments = useQuery({
    queryKey: ["comments", workspaceId, subjectType, subjectId],
    queryFn: () => listComments(workspaceId, subjectType, subjectId),
    enabled: open,
  });
  const members = useQuery({
    queryKey: ["members", workspaceId],
    queryFn: () => listMembers(workspaceId),
    enabled: open,
  });
  const items = comments.data ?? [];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent aria-label={t("boardCollaboration")}>
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <MessageSquare size={16} className="shrink-0 text-muted-foreground" />
            {t("boardCollaboration")}
            {/* 条数跟在标题后面,不另起一行:它是标题的一部分,不是一条独立的信息。 */}
            {items.length > 0 && (
              <span className="rounded-full bg-secondary px-1.5 text-ui-2xs font-semibold tabular-nums text-muted-foreground">
                {items.length}
              </span>
            )}
          </SheetTitle>
          <SheetDescription>{t("boardCollaborationHint")}</SheetDescription>
        </SheetHeader>

        <div className="min-h-0 overflow-y-auto overscroll-contain">
          {comments.isPending ? (
            <div className="grid gap-3 p-4">
              {[0, 1, 2].map((row) => (
                <Skeleton key={row} className="h-24 rounded-lg" />
              ))}
            </div>
          ) : items.length === 0 ? (
            // 空态只写一次。此前左右两栏各写了一遍,读起来像是出了两个不同的问题。
            <div className="grid content-start justify-items-center gap-2 px-8 py-16 text-center">
              <MessageSquare size={22} className="text-muted-foreground" />
              <p className="m-0 text-ui-sm font-medium">{t("commentsEmpty")}</p>
              <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("boardCommentModeHint")}</p>
            </div>
          ) : (
            <ol className="m-0 grid list-none gap-2 p-3">
              {items.map((comment, index) => (
                <li
                  key={comment.id}
                  className="grid gap-2.5 rounded-lg border border-divider bg-secondary/25 px-3.5 py-3 transition-colors hover:border-border-strong"
                >
                  <div className="flex items-center gap-2.5">
                    <span className="grid size-7 shrink-0 place-items-center rounded-full bg-primary/12 text-ui-2xs font-semibold text-primary">
                      {actorName(comment.author, t("teamSystemActor")).slice(0, 1).toUpperCase()}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-ui-sm font-semibold">
                      {actorName(comment.author, t("teamSystemActor"))}
                    </span>
                    <span className="shrink-0 text-ui-2xs tabular-nums text-muted-foreground">
                      {relativeTime(comment.created_at, locale)}
                    </span>
                  </div>

                  {/* 正文走和画布上那张卡同一个渲染器 —— @ 提及在两处必须长得一样。 */}
                  <CommentContent comment={comment} members={members.data?.members ?? []} />

                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-ui-2xs text-muted-foreground">
                    <span className="tabular-nums">#{index + 1}</span>
                    {comment.anchor?.node_id && (
                      <span className="flex min-w-0 items-center gap-1">
                        <MapPin size={11} className="shrink-0" />
                        <span className="truncate">{comment.anchor.node_id}</span>
                      </span>
                    )}
                    {comment.mentioned_user_ids.length > 0 && (
                      <span className="flex items-center gap-1">
                        <AtSign size={11} className="shrink-0" />
                        <span className="tabular-nums">{comment.mentioned_user_ids.length}</span>
                      </span>
                    )}
                    {locatable(comment) && (
                      <Button
                        variant="ghost"
                        size="xs"
                        className="ml-auto -mr-1.5"
                        onClick={() => onJumpToComment(comment)}
                      >
                        <LocateFixed size={12} /> {t("boardDiscussionJump")}
                      </Button>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
