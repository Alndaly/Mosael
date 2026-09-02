import type { BoardItem } from "@/api/client";

export type BoardItemRunStatus = NonNullable<BoardItem["run"]>["status"];

export function itemJobId(item: BoardItem): string | undefined {
  return item.run?.job_id;
}

export function itemError(item: BoardItem): string | undefined {
  return item.run?.error;
}

/** 所有画布节点共用的六态解释。 */
export function itemRunStatus(item: BoardItem): BoardItemRunStatus {
  return item.run?.status ?? "idle";
}

export function itemIsRunning(item: BoardItem): boolean {
  const status = itemRunStatus(item);
  // 轮询必须有可查询的 job；显式状态仍可用于节点视觉，但不能凭一个缺失 job_id 的脏快照
  // 启动永远无法收敛的 polling。
  return Boolean(itemJobId(item)) && (status === "queued" || status === "running");
}

export function runningState(jobId: string): NonNullable<BoardItem["run"]> {
  return { status: "running", job_id: jobId };
}

/** 服务端轮询到终态后写回本地节点的补丁。成功必须连同服务端已重置的 form 一起落下。 */
export function boardSettlementPatch(item: BoardItem): Partial<BoardItem> | null {
  if (item.asset_id) {
    return {
      asset_id: item.asset_id,
      form: item.form,
      run: item.run ?? { status: "succeeded" },
    };
  }
  const error = itemError(item);
  if (error) {
    return {
      run: item.run ?? { status: "failed", error },
    };
  }
  return null;
}

/**
 * Composer 的局部交互状态只在“节点拿到一份新产物”时重建。
 *
 * 不能把整个 item/form stringify 进 key：每敲一个字、拖一下节点都会 remount，光标与手动选择
 * 立刻丢失。失败/取消也不换 key，输入要留给重试；成功产生新 asset、或手动换素材，才说明
 * 上一次编辑周期已经结束。持久表单本身仍在节点上，重建后从它重新水合。
 */
export function itemFormResetKey(item: BoardItem): string {
  const completed = item.run?.status === "succeeded" ? "completed" : "draft";
  return `${item.id}:${item.asset_id ?? "empty"}:${completed}`;
}
