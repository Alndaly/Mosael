import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type Job = components["schemas"]["JobOut"];
export type TaskEvent = components["schemas"]["TaskEventOut"];

export function listJobs(workspaceId: string): Promise<Job[]> {
  return api<Job[]>(`/api/jobs?workspace_id=${encodeURIComponent(workspaceId)}`);
}

export function getJob(jobId: string): Promise<Job> {
  return api<Job>(`/api/jobs/${jobId}`);
}

export function listJobEvents(jobId: string): Promise<TaskEvent[]> {
  return api<TaskEvent[]>(`/api/jobs/${jobId}/events`);
}

/** 中止一个还在跑的任务。**节点粒度** —— 正在执行的那一步跑完,引擎在下一个节点边界看到
 *  已取消就停下(见后端 domain/jobs.cancel_job);派生的子任务一并取消。 */
export function cancelJob(jobId: string): Promise<Job> {
  return api<Job>(`/api/jobs/${jobId}/cancel`, { method: "POST" });
}

/** 工作流 job 派生的子任务(发布/导出/转写/生成/配音),在任务详情里「收纳」展示。 */
export function listJobChildren(jobId: string): Promise<Job[]> {
  return api<Job[]>(`/api/jobs/${jobId}/children`);
}

export type JobKind = components["schemas"]["JobKindOut"];
export type JobKindCatalog = components["schemas"]["JobKindCatalogOut"];

/** 任务种类目录:名字(已按语言翻好)、做完要不要说、改动了什么、在哪一页看。 */
export function fetchJobKinds(): Promise<JobKindCatalog> {
  return api<JobKindCatalog>("/api/jobs/kinds");
}
