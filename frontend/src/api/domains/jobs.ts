import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type Job = components["schemas"]["JobOut"];
export type TaskEvent = components["schemas"]["TaskEventOut"];

/**
 * 工作区的**顶层**任务(工作流派生的子任务收在父任务下,不平铺)—— 任务中心和定时任务页读的那一份。
 *
 * **键和取法写在一起,同一个键只有一种取法。** 此前任务中心拿 `["jobs", ws, "all"]` 拉顶层,
 * 定时任务页拿同一个键拉**全部**(含子任务):两边轮流覆盖同一份缓存,谁最后拉,缓存里就是谁的
 * 那份。任务中心每换回一次含子任务的那份,就看见一批「新出现、已经完成」的转写、导出 —— 按
 * 「快任务两次轮询之间就做完了」那条规则,把它们当成刚做完的,挨个弹一遍「已完成」。
 */
export function topLevelJobsQuery(workspaceId: string) {
  return {
    queryKey: ["jobs", workspaceId, "top-level"] as const,
    queryFn: () => api<Job[]>(`/api/jobs?workspace_id=${encodeURIComponent(workspaceId)}&top_level=true`),
  };
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
