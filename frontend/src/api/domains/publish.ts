import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type PublishPlatform = components["schemas"]["PublishPlatformOut"];
export type PublishAccount = components["schemas"]["PublishAccountOut"];
export type PublishTask = components["schemas"]["PublishTaskOut"];
export type PublishCopy = components["schemas"]["PublishCopyResponse"];

export function listPublishPlatforms(): Promise<PublishPlatform[]> {
  return api<PublishPlatform[]>("/api/publish/platforms");
}

export function listPublishAccounts(workspaceId: string): Promise<PublishAccount[]> {
  return api<PublishAccount[]>(`/api/publish/accounts?workspace_id=${workspaceId}`);
}

export function createPublishAccount(body: {
  workspace_id: string;
  platform: string;
  name: string;
  config: Record<string, unknown>;
  proxy?: string | null;
}): Promise<PublishAccount> {
  return api<PublishAccount>("/api/publish/accounts", { method: "POST", body: JSON.stringify(body) });
}

export function deletePublishAccount(accountId: string): Promise<unknown> {
  return api(`/api/publish/accounts/${accountId}`, { method: "DELETE" });
}

export function patchPublishAccount(
  accountId: string,
  body: { name?: string; enabled?: boolean; proxy?: string | null },
): Promise<PublishAccount> {
  return api<PublishAccount>(`/api/publish/accounts/${accountId}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function recheckPublishAccount(accountId: string): Promise<PublishAccount> {
  return api<PublishAccount>(`/api/publish/accounts/${accountId}/recheck`, { method: "POST" });
}

/**
 * 桌面执行器还在不在。
 *
 * 它是**另一个进程**(Electron 主进程里的发布执行器),后端只负责排队 —— 执行器没起来的话,
 * 任务就停在 queued 上不动,而界面此前对此一个字都不说:用户看到的是"发布了但什么都没发生"。
 * 这条接口一直存在,而它的**唯一调用方是它自己的测试**(见进程审计 2.10)。
 */
export function publishWorkerOnline(): Promise<{ online: boolean }> {
  return api<{ online: boolean }>("/api/publish/worker/status");
}

export function listPublishTasks(workspaceId: string): Promise<PublishTask[]> {
  return api<PublishTask[]>(`/api/publish/tasks?workspace_id=${workspaceId}`);
}

export function createPublishTask(body: {
  workspace_id: string;
  account_id: string;
  asset_id: string;
  title: string;
  description: string;
  tags: string[];
  short_title?: string;
  options?: Record<string, unknown>;
}): Promise<PublishTask> {
  return api<PublishTask>("/api/publish/tasks", { method: "POST", body: JSON.stringify(body) });
}

export function deletePublishTask(taskId: string): Promise<unknown> {
  return api(`/api/publish/tasks/${taskId}`, { method: "DELETE" });
}

export function generatePublishCopy(body: {
  workspace_id: string;
  asset_id?: string | null;
  brief?: string;
}): Promise<PublishCopy> {
  return api<PublishCopy>("/api/publish/copy", { method: "POST", body: JSON.stringify(body) });
}
