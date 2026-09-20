/**
 * 画布上标节点状态的那一次运行,是哪一次。
 *
 * 单独成文件是因为这个选择**出错时不会报错**:它只会让界面安静地不动,而"工作流正在跑但画布
 * 一片静止"和"确实没在跑"长得一模一样。放在 WorkflowsView 的一个 useMemo 里,没有任何测试
 * 够得着它。
 */

import type { Job } from "@/api/client";

/** 还没跑完的那几种状态。和 WorkflowRunHistory / JobChildren 同一套判据。 */
export const RUN_ACTIVE = new Set(["queued", "running", "pending"]);

/**
 * `startedId` 是这一页自己点「运行」起的那次;`runs` 是这个工作流的运行历史(**新的在前**)。
 *
 * 顺序即优先级:自己起的 → 还在跑的 → 最近的一次。中间那条是这次要修的:子工作流由父流程的
 * `call_workflow` 起来,这一页从没调用过 run,此前因此一个节点状态都没有。
 */
export function boundRunId(startedId: string | null, runs: Job[] | undefined): string | null {
  if (startedId) return startedId;
  const list = runs ?? [];
  return (list.find((one) => RUN_ACTIVE.has(one.status)) ?? list[0])?.id ?? null;
}
