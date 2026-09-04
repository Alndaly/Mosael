import React from "react";
import { useQuery } from "@tanstack/react-query";
import { LocateFixed, MessageSquare } from "lucide-react";

import {
  listComments,
  type Board,
  type CollaborationActor,
  type CollaborationComment,
} from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { relativeTime } from "@/lib/time";

function actorName(actor: CollaborationActor | null, systemName: string): string {
  return actor?.display_name || actor?.username || systemName;
}

export function BoardCollaborationDialog({
  open,
  onOpenChange,
  board,
  onJumpToComment,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  board: Board;
  onJumpToComment: (comment: CollaborationComment) => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const subject = [board.workspace_id, "board", board.id] as const;
  const commentsKey = ["comments", ...subject];
  const comments = useQuery({
    queryKey: commentsKey,
    queryFn: () => listComments(...subject),
    enabled: open,
  });
  const [selectedCommentId, setSelectedCommentId] = React.useState<string | null>(null);
  const commentItems = comments.data ?? [];
  const selectedComment = commentItems.find((item) => item.id === selectedCommentId) ?? commentItems[0] ?? null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="h-[min(680px,calc(100vh-32px))] w-[min(900px,calc(100vw-32px))] max-w-[calc(100vw-32px)] grid-rows-[auto_minmax(0,1fr)] gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b border-border px-6 py-5 pr-14">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-1.5">
              <DialogTitle className="flex items-center gap-2"><MessageSquare size={18} /> {t("boardCollaboration")}</DialogTitle>
              <DialogDescription>{t("boardCollaborationHint")}</DialogDescription>
            </div>
            <div className="flex items-center gap-2 text-ui-xs text-muted-foreground">
              <span className="rounded-full border border-border bg-secondary/40 px-2.5 py-1">{t("discussionCount").replace("{count}", String(commentItems.length))}</span>
            </div>
          </div>
        </DialogHeader>
        <div className="grid min-h-0 grid-cols-1 md:grid-cols-[300px_minmax(0,1fr)]">
          <nav
            aria-label={t("discussionNavigation")}
            className="flex min-h-0 flex-col border-b border-border bg-secondary/10 md:border-b-0 md:border-r"
          >
            <div className="border-b border-border px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-ui-sm font-semibold">{t("discussionList")}</h3>
                <span className="text-ui-xs tabular-nums text-muted-foreground">{commentItems.length}</span>
              </div>
              <p className="mt-1 text-ui-xs leading-relaxed text-muted-foreground">{t("discussionListHint")}</p>
            </div>
            <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
              {commentItems.map((item, index) => (
                <button
                  key={item.id}
                  type="button"
                  aria-current={selectedComment?.id === item.id ? "true" : undefined}
                  className="group flex w-full gap-3 rounded-lg border border-transparent px-3 py-2.5 text-left transition-colors hover:bg-secondary/50 aria-[current=true]:border-border-strong aria-[current=true]:bg-secondary/70"
                  onClick={() => setSelectedCommentId(item.id)}
                >
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-primary/12 text-ui-2xs font-semibold text-primary">
                    {actorName(item.author, t("teamSystemActor")).slice(0, 1).toUpperCase()}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-2 text-ui-xs">
                      <span className="truncate font-semibold text-foreground">{actorName(item.author, t("teamSystemActor"))}</span>
                      <span className="shrink-0 text-muted-foreground">{relativeTime(item.created_at, locale)}</span>
                    </span>
                    <span className="mt-1 block line-clamp-2 text-ui-xs leading-relaxed text-muted-foreground">{item.body}</span>
                    <span className="mt-1.5 flex items-center gap-1 text-ui-2xs text-muted-foreground">
                      <span>#{index + 1}</span>
                      {item.anchor?.node_id && <><span>·</span><span className="truncate">{item.anchor.node_id}</span></>}
                    </span>
                  </span>
                </button>
              ))}
              {comments.isSuccess && commentItems.length === 0 && (
                <div className="grid place-items-center gap-2 px-5 py-12 text-center text-muted-foreground">
                  <MessageSquare size={20} />
                  <p className="text-ui-sm">{t("commentsEmpty")}</p>
                  <p className="text-ui-xs leading-relaxed">{t("boardCommentModeHint")}</p>
                </div>
              )}
            </div>
          </nav>

          <main className="min-h-0 overflow-y-auto px-5 py-5 sm:px-6">
            <section
              role="region"
              aria-label={t("currentDiscussion")}
              className="space-y-5"
            >
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <p className="text-ui-xs font-medium uppercase tracking-wide text-muted-foreground">{t("currentDiscussion")}</p>
                  <h3 className="mt-1 text-ui-md font-semibold">{selectedComment ? actorName(selectedComment.author, t("teamSystemActor")) : t("commentsEmpty")}</h3>
                </div>
                {selectedComment && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={typeof selectedComment.anchor?.x !== "number" || typeof selectedComment.anchor?.y !== "number"}
                    onClick={() => onJumpToComment(selectedComment)}
                    aria-label={t("boardDiscussionJump")}
                  >
                    <LocateFixed size={14} /> {t("boardDiscussionJump")}
                  </Button>
                )}
              </div>
              {selectedComment ? (
                <div className="overflow-hidden rounded-xl border border-border bg-secondary/15">
                  <div className="flex items-center gap-3 border-b border-border px-4 py-3">
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary/12 text-ui-xs font-semibold text-primary">
                      {actorName(selectedComment.author, t("teamSystemActor")).slice(0, 1).toUpperCase()}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-ui-sm font-semibold">{actorName(selectedComment.author, t("teamSystemActor"))}</p>
                      <p className="text-ui-xs text-muted-foreground">{relativeTime(selectedComment.created_at, locale)}</p>
                    </div>
                  </div>
                  <p className="whitespace-pre-wrap px-4 py-5 text-ui-sm leading-7 text-foreground">{selectedComment.body}</p>
                  {(selectedComment.anchor?.node_id || selectedComment.mentioned_user_ids.length > 0) && (
                    <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3 text-ui-xs text-muted-foreground">
                      {selectedComment.anchor?.node_id && (
                        <span className="rounded-full bg-secondary px-2 py-0.5">{t("discussionAttachedNode")} · {selectedComment.anchor.node_id}</span>
                      )}
                      {selectedComment.mentioned_user_ids.length > 0 && (
                        <span>{t("discussionMentionCount").replace("{count}", String(selectedComment.mentioned_user_ids.length))}</span>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-border px-5 py-8 text-center text-ui-sm text-muted-foreground">
                  {t("discussionEmpty")}
                </div>
              )}
              <div className="rounded-xl border border-dashed border-border px-4 py-3 text-ui-xs leading-relaxed text-muted-foreground">
                {t("discussionCanvasHint")}
              </div>
            </section>
          </main>
        </div>
      </DialogContent>
    </Dialog>
  );
}
