import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type CollaborationActor = components["schemas"]["ActorOut"];

export type ActivityEvent = components["schemas"]["ActivityOut"];

export type CollaborationComment = components["schemas"]["CommentOut"];

export type CollaborationCommentAnchor = components["schemas"]["CanvasCommentAnchor"];

function subjectQuery(workspaceId: string, subjectType: string, subjectId: string): string {
  return new URLSearchParams({ workspace_id: workspaceId, subject_type: subjectType, subject_id: subjectId }).toString();
}

export function listActivity(workspaceId: string, subjectType?: string, subjectId?: string): Promise<ActivityEvent[]> {
  const params = new URLSearchParams({ workspace_id: workspaceId, limit: "50" });
  if (subjectType) params.set("subject_type", subjectType);
  if (subjectId) params.set("subject_id", subjectId);
  return api<ActivityEvent[]>(`/api/activity?${params}`);
}

export function listComments(workspaceId: string, subjectType: string, subjectId: string): Promise<CollaborationComment[]> {
  return api<CollaborationComment[]>(`/api/comments?${subjectQuery(workspaceId, subjectType, subjectId)}`);
}

export function addComment(body: {
  workspace_id: string;
  subject_type: "board" | "workflow" | "sequence" | "asset";
  subject_id: string;
  body: string;
  mentioned_user_ids?: string[];
  anchor?: CollaborationCommentAnchor;
  body_document?: Record<string, unknown>;
}): Promise<CollaborationComment> {
  return api<CollaborationComment>("/api/comments", { method: "POST", body: JSON.stringify(body) });
}

export function moveComment(commentId: string, body: {
  workspace_id: string;
  anchor: CollaborationCommentAnchor;
}): Promise<CollaborationComment> {
  return api<CollaborationComment>(`/api/comments/${commentId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function editComment(commentId: string, body: {
  workspace_id: string;
  body: string;
  body_document: Record<string, unknown>;
  mentioned_user_ids: string[];
}): Promise<CollaborationComment> {
  return api<CollaborationComment>(`/api/comments/${commentId}/content`, { method: "PUT", body: JSON.stringify(body) });
}

export function deleteComment(commentId: string, workspaceId: string): Promise<void> {
  return api<void>(`/api/comments/${commentId}?workspace_id=${encodeURIComponent(workspaceId)}`, {
    method: "DELETE",
  });
}

