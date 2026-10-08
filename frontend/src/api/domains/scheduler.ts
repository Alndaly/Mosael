import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type ScheduledTask = components["schemas"]["ScheduledTaskOut"];
export type ScheduledTaskRun = components["schemas"]["ScheduledTaskRunOut"];
/** 绑着某张工作流(或调用它的图)、在等主人认可的一个定时任务(ADR 0047)。 */
export type TaskAwaitingApproval = components["schemas"]["TaskAwaitingApprovalOut"];
export type RunScheduledTaskResponse = components["schemas"]["RunScheduledTaskResponse"];
export type ScheduledTaskCreate = components["schemas"]["ScheduledTaskCreate"];
export type ScheduledTaskUpdate = components["schemas"]["ScheduledTaskUpdate"];
export type ScheduledTaskCreateInput = Omit<ScheduledTaskCreate, "timezone" | "enabled"> &
  Partial<Pick<ScheduledTaskCreate, "timezone" | "enabled">>;

export function listScheduledTasks(workspaceId: string, projectId?: string | null): Promise<ScheduledTask[]> {
  const query = new URLSearchParams({ workspace_id: workspaceId });
  if (projectId) query.set("project_id", projectId);
  return api<ScheduledTask[]>(`/api/scheduled-tasks?${query}`);
}

export function createScheduledTask(body: ScheduledTaskCreateInput): Promise<ScheduledTask> {
  return api<ScheduledTask>("/api/scheduled-tasks", { method: "POST", body: JSON.stringify(body) });
}

export function updateScheduledTask(taskId: string, body: ScheduledTaskUpdate): Promise<ScheduledTask> {
  return api<ScheduledTask>(`/api/scheduled-tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteScheduledTask(taskId: string): Promise<void> {
  return api<void>(`/api/scheduled-tasks/${taskId}`, { method: "DELETE" });
}

export function runScheduledTask(taskId: string): Promise<RunScheduledTaskResponse> {
  return api<RunScheduledTaskResponse>(`/api/scheduled-tasks/${taskId}/run`, { method: "POST" });
}

/** 重置触发密钥:旧的触发地址(连同查进度、取消)立刻失效。 */
export function resetWebhookSecret(taskId: string): Promise<ScheduledTask> {
  return api<ScheduledTask>(`/api/scheduled-tasks/${taskId}/webhook-secret`, { method: "POST" });
}

export function listScheduledTaskRuns(taskId: string): Promise<ScheduledTaskRun[]> {
  return api<ScheduledTaskRun[]>(`/api/scheduled-tasks/${taskId}/runs`);
}

/**
 * 这张工作流被谁的定时任务绑着、那个任务此刻在等主人认可哪一版(ADR 0047):编辑器据此提醒改图的人
 * 「你存的这一版要 A 认可之后,A 的任务才会接着用 A 的 AI 连接」。只列我看得见的任务。
 */
export function listTasksAwaitingApproval(workflowId: string): Promise<TaskAwaitingApproval[]> {
  return api<TaskAwaitingApproval[]>(`/api/workflows/${workflowId}/awaiting-approvals`);
}

/** 上面那份清单的缓存键。认可一版、存一版之后都要失效它。 */
export const tasksAwaitingApprovalKey = (workflowId: string) => ["workflow-awaiting-approvals", workflowId] as const;
