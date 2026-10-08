import type { MessageKey } from "@/app/messages";

/**
 * 任务(一次运行)状态的叫法 —— **只有这一张表**。任务详情、子任务清单、定时任务、工作流执行历史
 * 都从这里取。
 *
 * 此前各处写 `` t(`runStatus_${status}` as never) ``:后端多一种状态,界面上就露出 `runStatus_xxx`
 * 这串键名,而类型检查一声不吭。这里不认识的状态返回 null,调用方原样显示状态值。
 *
 * 这是**任务**的状态;工作流里某一步的状态(done / skipped …)是另一组,见 features/workflows/runSteps
 * 的 STEP_STATUS_LABELS。
 */
const RUN_STATUS_LABELS: Readonly<Record<string, MessageKey>> = {
  queued: "runStatus_queued",
  running: "runStatus_running",
  succeeded: "runStatus_succeeded",
  failed: "runStatus_failed",
  cancelled: "runStatus_cancelled",
};

export function runStatusLabelKey(status: string): MessageKey | null {
  return Object.hasOwn(RUN_STATUS_LABELS, status) ? RUN_STATUS_LABELS[status] : null;
}

/** 状态的显示文字:认识的翻译,不认识的原样给,不吞掉。 */
export function runStatusText(t: (key: MessageKey) => string, status: string): string {
  const key = runStatusLabelKey(status);
  return key ? t(key) : status;
}

/**
 * 任务的终态:成功、失败、**被停下**(`cancelled`,ADR 0049)。和后端 `jobs.TERMINAL_STATUSES` 是同一组。
 *
 * 轮询「它结束了没有」的地方都问这一处。此前各处自己写「成功或失败」两种:被停下有了自己的状态之后,
 * 漏改的那一处会把一个被停下的任务当成「还在跑」,一直轮询下去(棘轮:runStatus.test.ts)。
 */
export const TERMINAL_JOB_STATUSES: ReadonlySet<string> = new Set(["succeeded", "failed", "cancelled"]);

export function jobSettled(status: string | undefined): boolean {
  return status !== undefined && TERMINAL_JOB_STATUSES.has(status);
}
