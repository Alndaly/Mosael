import { CANVAS_WINDOW_SURFACE_CLASS } from "@/components/app/canvasPanelLayout";
import React from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import type { CollaborationComment, WorkspaceMember } from "@/api/client";
import { editComment } from "@/api/domains/collaboration";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { BoardCommentComposer, type CommentDraft } from "./BoardCommentComposer";
import { CommentMembers, commentDocument, commentExtensions, COMMENT_TEXT } from "./commentDocument";

export function CommentContent({ comment, members }: { comment: CollaborationComment; members: WorkspaceMember[] }) {
  const editor = useEditor({ extensions: commentExtensions(), content: commentDocument(comment), editable: false,
    editorProps: { attributes: { class: cn(COMMENT_TEXT, "outline-none") } } });
  React.useEffect(() => { editor?.commands.setContent(commentDocument(comment), { emitUpdate: false }); }, [editor, comment.body, comment.body_document]);
  return <CommentMembers.Provider value={members}><EditorContent editor={editor} /></CommentMembers.Provider>;
}

export function CommentCard({ comment, members, currentUserId, onDelete, onClose }: {
  comment: CollaborationComment; members: WorkspaceMember[]; currentUserId?: string | null;
  onDelete?: () => Promise<unknown>; onClose?: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [editing, setEditing] = React.useState(false);
  const own = Boolean(currentUserId && currentUserId === comment.author_id);
  const save = useMutation({
    mutationFn: (draft: CommentDraft) => editComment(comment.id, { workspace_id: comment.workspace_id,
      body: draft.body, body_document: draft.bodyDocument, mentioned_user_ids: draft.mentionedUserIds }),
    onSuccess: updated => {
      qc.setQueryData<CollaborationComment[]>(["comments", comment.workspace_id, comment.subject_type, comment.subject_id],
        current => current?.map(one => one.id === updated.id ? updated : one));
      void qc.invalidateQueries({ queryKey: ["activity", comment.workspace_id] });
      setEditing(false);
    },
    onError: error => toast.error(String(error)),
  });
  const remove = useMutation({ mutationFn: async () => onDelete?.(), onError: error => toast.error(String(error)) });
  if (editing && own) return <BoardCommentComposer key={comment.id} members={members} initialContent={commentDocument(comment)} editing
    onSubmit={draft => save.mutateAsync(draft)} onCancel={() => setEditing(false)} />;
  return <div data-board-comment-overlay="" className={cn(CANVAS_WINDOW_SURFACE_CLASS, "nodrag nopan nowheel pointer-events-auto w-72 overflow-hidden text-left")}
    onPointerDown={event => event.stopPropagation()} onMouseDown={event => event.stopPropagation()} onClick={event => event.stopPropagation()}>
    <div className="flex h-11 items-center gap-1 border-b border-border px-3">
      <span className="min-w-0 flex-1 truncate text-ui-xs font-medium">{comment.author?.display_name || comment.author?.username || t("teamSystemActor")}</span>
      {own && <Button variant="ghost" size="icon-xs" aria-label={t("commentEdit")} onClick={() => setEditing(true)}><Pencil size={13} /></Button>}
      {own && onDelete && <Button variant="ghost" size="icon-xs" data-delete-comment="" aria-label={t("delete")} loading={remove.isPending}
        className="hover:bg-destructive/10 hover:text-destructive" onClick={() => remove.mutate()}><Trash2 size={13} /></Button>}
      {onClose && <Button variant="ghost" size="icon-xs" aria-label={t("close")} onClick={onClose}><X size={13} /></Button>}
    </div>
    <div className="max-h-64 overflow-y-auto px-3 py-3"><CommentContent comment={comment} members={members} /></div>
  </div>;
}
