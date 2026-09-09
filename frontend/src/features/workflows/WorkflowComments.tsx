import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ViewportPortal } from "@xyflow/react";
import { toast } from "sonner";
import { addComment, deleteComment, listComments, listMembers } from "@/api/client";
import { useAuth } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { CommentCard } from "@/features/boards/CommentCard";
import { BoardCommentComposer, type CommentDraft } from "@/features/boards/BoardCommentComposer";
import { AnnotationControls } from "@/features/markers/AnnotationControls";

type Point = { x: number; y: number; node_id?: string };

export function useWorkflowComments(workspaceId: string, workflowId: string) {
  const [active, setActive] = React.useState(false);
  const [visible, setVisible] = React.useState(true);
  const [draft, setDraft] = React.useState<Point | null>(null);
  const [selected, setSelected] = React.useState<string | null>(null);
  const { user } = useAuth();
  const t = useI18n();
  const qc = useQueryClient();
  const key = ["comments", workspaceId, "workflow", workflowId];
  const comments = useQuery({ queryKey: key, queryFn: () => listComments(workspaceId, "workflow", workflowId) });
  const members = useQuery({ queryKey: ["members", workspaceId], queryFn: () => listMembers(workspaceId), enabled: active });
  const remove = useMutation({
    mutationFn: (id: string) => deleteComment(id, workspaceId),
    onSuccess: () => { setSelected(null); void qc.invalidateQueries({ queryKey: key }); },
    onError: error => toast.error(String(error)),
  });
  const exit = () => { setActive(false); setDraft(null); setSelected(null); };
  const place = (point: Point) => {
    if (!active) return;
    if (draft || selected) { setDraft(null); setSelected(null); return; }
    setDraft(point);
  };
  const submit = async (value: CommentDraft) => {
    if (!draft) return;
    try {
      const result = await addComment({ workspace_id: workspaceId, subject_type: "workflow", subject_id: workflowId,
        body: value.body, mentioned_user_ids: value.mentionedUserIds, body_document: value.bodyDocument,
        anchor: { kind: "canvas", ...draft } });
      await qc.invalidateQueries({ queryKey: key });
      setDraft(null); setSelected(result.id);
    } catch (error) { toast.error(String(error)); throw error; }
  };
  const layer = visible && <ViewportPortal>
    {(comments.data ?? []).map((comment, index) => {
      const { x, y } = comment.anchor ?? {};
      if (typeof x !== "number" || typeof y !== "number") return null;
      return <div key={comment.id} data-workflow-comment="" className="nodrag nopan pointer-events-none absolute z-20 flex items-start gap-2" style={{ left: x, top: y }}
        onPointerDown={e => e.stopPropagation()} onMouseDown={e => e.stopPropagation()} onClick={e => e.stopPropagation()}>
        <button style={{ pointerEvents: active ? "auto" : "none" }} tabIndex={active ? 0 : -1} className="grid size-7 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-border-strong bg-panel text-ui-xs text-foreground shadow-sm" aria-label={`${t("comments")} ${index + 1}`} title={comment.body}
          onClick={() => { setDraft(null); setSelected(selected === comment.id ? null : comment.id); }}>{index + 1}</button>
        {active && selected === comment.id && <div className="-translate-y-3">
          <CommentCard comment={comment} members={members.data?.members ?? []} currentUserId={user?.id}
            onDelete={() => remove.mutateAsync(comment.id)} onClose={() => setSelected(null)} />
        </div>}
      </div>;
    })}
    {active && draft && <div className="nodrag nopan nowheel pointer-events-auto absolute z-30 w-72" style={{ left: draft.x, top: draft.y }}
      onPointerDown={e => e.stopPropagation()} onMouseDown={e => e.stopPropagation()} onClick={e => e.stopPropagation()}>
      <BoardCommentComposer members={members.data?.members ?? []} onSubmit={submit} onCancel={() => setDraft(null)} />
    </div>}
  </ViewportPortal>;
  /** 从讨论侧栏跳过来:进评论模式、把批注显出来、选中它。视口居中归调用方(它才有 RF 实例)。 */
  const focus = (id: string) => { setActive(true); setVisible(true); setDraft(null); setSelected(id); };
  return { active, exit, place, layer, focus,
    controls: (onEnter: () => void) => <AnnotationControls kind="comment" active={active} visible={visible}
      onMode={() => { if (active) exit(); else { onEnter(); setActive(true); setVisible(true); } }}
      onVisible={() => { if (visible) exit(); setVisible(!visible); }} />,
  };
}
