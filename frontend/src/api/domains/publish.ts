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
