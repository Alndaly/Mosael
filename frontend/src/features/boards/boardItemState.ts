import type { BoardItem } from "@/api/client";

/** 旧画布会在第一次保存时由后端迁到 run；前端在那之前也必须正确显示。 */
export function itemJobId(item: BoardItem): string | undefined {
  return item.run?.job_id ?? item.job_id;
}

export function itemError(item: BoardItem): string | undefined {
  return item.run?.error ?? item.error;
}

export function itemIsRunning(item: BoardItem): boolean {
  return Boolean(itemJobId(item)) && (item.run?.status === undefined || item.run.status === "queued" || item.run.status === "running");
}

export function runningState(jobId: string): NonNullable<BoardItem["run"]> {
  return { status: "running", job_id: jobId };
}

