/**
 * 确认卡:智能体要做一件改东西、花钱或对外的事之前,先落一张卡等人批(后端 `routes/confirmations.py`)。
 * 缓存键见 `api/queryKeys.confirmationKeys`。
 */
import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type Confirmation = components["schemas"]["ConfirmationOut"];
export type ConfirmationStatus = "pending" | "approved" | "executed" | "failed" | "rejected";

/**
 * 一个工作区里的卡,按状态筛(不给就不筛);带会话 id 就只要那次对话的。
 * `decidable`:只要**我能拍板**的 —— 列出来的每一张批 / 拒都不会被权限挡回(共享来的对话里的卡看得见、批不了,不在其中)。
 * `automatic`:只要**没问人就放行了**的(`decision_mode` 不是 manual),不论后来执行成没成。
 */
export function listConfirmations(query: {
  workspaceId: string;
  status?: ConfirmationStatus;
  sessionId?: string;
  decidable?: boolean;
  automatic?: boolean;
  limit?: number;
}): Promise<Confirmation[]> {
  const params = new URLSearchParams({ workspace_id: query.workspaceId });
  if (query.status) params.set("status", query.status);
  if (query.sessionId) params.set("session_id", query.sessionId);
  if (query.decidable) params.set("decidable", "true");
  if (query.automatic) params.set("automatic", "true");
  if (query.limit != null) params.set("limit", String(query.limit));
  return api<Confirmation[]>(`/api/confirmations?${params}`);
}

export function approveConfirmation(confirmationId: string): Promise<Confirmation> {
  return api<Confirmation>(`/api/confirmations/${confirmationId}/approve`, { method: "POST" });
}

export function rejectConfirmation(confirmationId: string): Promise<Confirmation> {
  return api<Confirmation>(`/api/confirmations/${confirmationId}/reject`, { method: "POST" });
}
