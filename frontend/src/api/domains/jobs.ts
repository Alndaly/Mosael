import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type Job = components["schemas"]["JobOut"];
export type TaskEvent = components["schemas"]["TaskEventOut"];

export function getJob(jobId: string): Promise<Job> {
  return api<Job>(`/api/jobs/${jobId}`);
}

export function listJobEvents(jobId: string): Promise<TaskEvent[]> {
  return api<TaskEvent[]>(`/api/jobs/${jobId}/events`);
}

/** 工作流 job 派生的子任务(发布/导出/转写/生成/配音),在任务详情里「收纳」展示。 */
export function listJobChildren(jobId: string): Promise<Job[]> {
  return api<Job[]>(`/api/jobs/${jobId}/children`);
}
