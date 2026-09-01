import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type ScheduledTask = components["schemas"]["ScheduledTaskOut"];
export type ScheduledTaskRun = components["schemas"]["ScheduledTaskRunOut"];
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

export function listScheduledTaskRuns(taskId: string): Promise<ScheduledTaskRun[]> {
  return api<ScheduledTaskRun[]>(`/api/scheduled-tasks/${taskId}/runs`);
}
