import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, LocateFixed, MessageSquare, RotateCcw } from "lucide-react";
import { toast } from "sonner";

import {
  decideReview,
  listComments,
  listMembers,
  listReviews,
  requestReview,
  type Board,
  type CollaborationActor,
  type CollaborationComment,
} from "@/api/client";
import { useAuth } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
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
  const { user } = useAuth();
  const qc = useQueryClient();
  const subject = [board.workspace_id, "board", board.id] as const;
  const commentsKey = ["comments", ...subject];
  const reviewsKey = ["reviews", ...subject];
  const comments = useQuery({
    queryKey: commentsKey,
    queryFn: () => listComments(...subject),
    enabled: open,
  });
  const reviews = useQuery({
    queryKey: reviewsKey,
    queryFn: () => listReviews(...subject),
    enabled: open,
  });
  const members = useQuery({
    queryKey: ["members", board.workspace_id],
    queryFn: () => listMembers(board.workspace_id),
    enabled: open,
  });
  const [reviewer, setReviewer] = React.useState("");
  const [reviewNote, setReviewNote] = React.useState("");
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: commentsKey });
    void qc.invalidateQueries({ queryKey: reviewsKey });
    void qc.invalidateQueries({ queryKey: ["activity", board.workspace_id] });
  };
  const reviewMut = useMutation({
    mutationFn: () => requestReview({
      workspace_id: board.workspace_id,
      subject_type: "board",
      subject_id: board.id,
      reviewer_id: reviewer,
      note: reviewNote,
    }),
    onSuccess: () => { setReviewNote(""); refresh(); },
    onError: (error: Error) => toast.error(error.message),
  });
  const decideMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "approved" | "changes_requested" }) => decideReview(id, status),
    onSuccess: refresh,
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[min(760px,calc(100vh-32px))] w-[min(720px,calc(100vw-32px))] max-w-[calc(100vw-32px)] grid-rows-[auto_minmax(0,1fr)] overflow-hidden p-0">
        <DialogHeader className="border-b border-border px-5 py-4">
          <DialogTitle className="flex items-center gap-2"><MessageSquare size={17} /> {t("boardCollaboration")}</DialogTitle>
          <DialogDescription>{t("boardCollaborationHint")}</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 space-y-6 overflow-y-auto px-5 pb-5">
          <section className="space-y-3 pt-1">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-ui-md font-semibold">{t("comments")}</h3>
              <span className="text-ui-xs text-muted-foreground">{comments.data?.length ?? 0}</span>
            </div>
            <div className="space-y-2">
              {(comments.data ?? []).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  disabled={typeof item.anchor?.x !== "number" || typeof item.anchor?.y !== "number"}
                  className="group w-full rounded-lg border border-border bg-secondary/30 px-3 py-2.5 text-left transition-colors enabled:hover:border-border-strong enabled:hover:bg-secondary/60 disabled:cursor-default"
                  onClick={() => onJumpToComment(item)}
                >
                  <div className="mb-1 flex items-center justify-between gap-3 text-ui-xs text-muted-foreground">
                    <span className="font-semibold text-foreground">{actorName(item.author, t("teamSystemActor"))}</span>
                    <span className="flex items-center gap-2">
                      {relativeTime(item.created_at, locale)}
                      {typeof item.anchor?.x === "number" && <LocateFixed size={13} className="transition-colors group-hover:text-primary" />}
                    </span>
                  </div>
                  <p className="whitespace-pre-wrap text-ui-sm leading-relaxed">{item.body}</p>
                  {item.anchor?.node_id && <p className="mt-1 truncate text-ui-2xs text-muted-foreground">{item.anchor.node_id}</p>}
                </button>
              ))}
              {comments.isSuccess && comments.data.length === 0 && <p className="text-ui-sm text-muted-foreground">{t("commentsEmpty")}</p>}
            </div>
            <p className="text-ui-xs text-muted-foreground">{t("boardReviewModeHint")}</p>
          </section>

          <section className="space-y-3 border-t border-border pt-5">
            <h3 className="text-ui-md font-semibold">{t("reviews")}</h3>
            <div className="space-y-2">
              {(reviews.data ?? []).map((review) => (
                <div key={review.id} className="flex items-start justify-between gap-3 rounded-lg border border-border px-3 py-2.5">
                  <div className="min-w-0 text-ui-sm">
                    <div><span className="font-semibold">{actorName(review.requester, t("teamSystemActor"))}</span> → {actorName(review.reviewer, t("teamSystemActor"))}</div>
                    {review.note && <p className="mt-1 text-muted-foreground">{review.note}</p>}
                    {review.decision_note && <p className="mt-1">{review.decision_note}</p>}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <Badge variant={review.status === "approved" ? "default" : "outline"}>{t(`review_${review.status}` as never)}</Badge>
                    {review.status === "pending" && review.reviewer_id === user?.id && (
                      <>
                        <Button size="icon" variant="ghost" loading={decideMut.isPending} onClick={() => decideMut.mutate({ id: review.id, status: "approved" })} aria-label={t("reviewApprove")}><Check size={14} /></Button>
                        <Button size="icon" variant="ghost" loading={decideMut.isPending} onClick={() => decideMut.mutate({ id: review.id, status: "changes_requested" })} aria-label={t("reviewChanges")}><RotateCcw size={14} /></Button>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <div className="grid gap-2 sm:grid-cols-[180px_1fr_auto]">
              <Select value={reviewer} onValueChange={setReviewer}>
                <SelectTrigger><SelectValue placeholder={t("reviewerPlaceholder")} /></SelectTrigger>
                <SelectContent>
                  {(members.data?.members ?? []).filter((member) => member.user_id !== user?.id).map((member) => (
                    <SelectItem key={member.user_id} value={member.user_id}>{member.display_name || member.username}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Textarea value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder={t("reviewNotePlaceholder")} rows={1} />
              <Button disabled={!reviewer} loading={reviewMut.isPending} onClick={() => reviewMut.mutate()}>{t("requestReview")}</Button>
            </div>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
