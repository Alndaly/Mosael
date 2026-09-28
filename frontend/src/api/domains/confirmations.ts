/**
 * 确认卡:智能体要做一件改东西、花钱或对外的事之前,先落一张卡等人批(后端 `routes/confirmations.py`)。
 * 缓存键见 `api/queryKeys.confirmationKeys`。
 */
import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type Confirmation = components["schemas"]["ConfirmationOut"];
export type ConfirmationStatus = "pending" | "approved" | "rejected";

/** 一个工作区里某种状态的卡;带会话 id 就只要那次对话的。 */
export function listConfirmations(query: {
  workspaceId: string;
  status: ConfirmationStatus;
  sessionId?: string;
  limit?: number;
}): Promise<Confirmation[]> {
  const params = new URLSearchParams({ workspace_id: query.workspaceId, status: query.status });
  if (query.sessionId) params.set("session_id", query.sessionId);
  if (query.limit != null) params.set("limit", String(query.limit));
  return api<Confirmation[]>(`/api/confirmations?${params}`);
}

export function approveConfirmation(confirmationId: string): Promise<Confirmation> {
  return api<Confirmation>(`/api/confirmations/${confirmationId}/approve`, { method: "POST" });
}

export function rejectConfirmation(confirmationId: string): Promise<Confirmation> {
  return api<Confirmation>(`/api/confirmations/${confirmationId}/reject`, { method: "POST" });
}
