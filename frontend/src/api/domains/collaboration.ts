import { api } from "@/api/transport";

export interface CollaborationActor {
  id: string | null;
  username: string;
  display_name: string;
  avatar_key: string;
}

export interface ActivityEvent {
  id: string;
  workspace_id: string;
  actor_id: string | null;
  actor: CollaborationActor | null;
  action: string;
  subject_type: string;
  subject_id: string;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface CollaborationComment {
  id: string;
  workspace_id: string;
  subject_type: string;
  subject_id: string;
  author_id: string | null;
  author: CollaborationActor | null;
  body: string;
  mentioned_user_ids: string[];
  anchor: CollaborationCommentAnchor | null;
  body_document: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CollaborationCommentAnchor {
  kind?: "canvas";
  x?: number;
  y?: number;
  node_id?: string;
}

export interface CollaborationReview {
  id: string;
  workspace_id: string;
  subject_type: string;
  subject_id: string;
  requested_by: string | null;
  requester: CollaborationActor | null;
  reviewer_id: string;
  reviewer: CollaborationActor | null;
  status: "pending" | "approved" | "changes_requested" | "cancelled";
  note: string;
  decision_note: string;
  decided_by: string | null;
  created_at: string;
  decided_at: string | null;
}

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

export function listReviews(workspaceId: string, subjectType: string, subjectId: string): Promise<CollaborationReview[]> {
  return api<CollaborationReview[]>(`/api/reviews?${subjectQuery(workspaceId, subjectType, subjectId)}`);
}

export function requestReview(body: {
  workspace_id: string;
  subject_type: "board" | "workflow" | "sequence" | "asset";
  subject_id: string;
  reviewer_id: string;
  note?: string;
}): Promise<CollaborationReview> {
  return api<CollaborationReview>("/api/reviews", { method: "POST", body: JSON.stringify(body) });
}

export function decideReview(reviewId: string, status: "approved" | "changes_requested" | "cancelled", note = ""): Promise<CollaborationReview> {
  return api<CollaborationReview>(`/api/reviews/${reviewId}/decision`, {
    method: "POST",
    body: JSON.stringify({ status, note }),
  });
}
