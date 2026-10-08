/**
 * 任务详情页头右边那两样:「立即运行」和启用开关。
 *
 * 单独成文件是为了能测「跑不起来的任务」这一档。此前绑的工作流被删了,页面上写着
 * 「绑定的工作流已删除」,开关却照样打得开、「立即运行」照样点得动 —— 每点一次,运行记录里
 * 多一条 0.0 秒的失败。后端现在会拒绝(scheduler.ensure_runnable),这里不该先摆出一个
 * 点了只会报错的按钮。
 */

import React from "react";
import { Play } from "lucide-react";

import type { ScheduledTaskRun } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Hint } from "@/components/ui/tooltip";

/**
 * 这个任务此刻有没有一次还没跑完 —— 和后端拒绝重入的判据一致(scheduler.executors.has_active_run,
 * queued / running)。「立即运行」按它判,而不是按这一页发出去的那一次请求:请求几十毫秒就回来了,
 * 任务却还在跑,此前转圈一停就又能点,连点几下后端才一次次回「还没跑完」。
 */
export function hasActiveRun(runs: readonly Pick<ScheduledTaskRun, "status">[] | undefined): boolean {
  return (runs ?? []).some((run) => run.status === "queued" || run.status === "running");
}

export function TaskRunControls({
  enabled,
  blocked,
  notOwner,
  running,
  onRun,
  onToggle,
}: {
  enabled: boolean;
  /** 跑不起来(绑的工作流已删除)。 */
  blocked: boolean;
  /** 不是这个任务的主人:为什么动不了(后端只许主人运行、启停,见 scheduler.manageable_task)。 */
  notOwner?: string;
  /** 有一次还在跑(或正在发起)。这时按钮说「运行中」、点不动 —— 定时任务不重入。 */
  running: boolean;
  onRun: () => void;
  onToggle: (enabled: boolean) => void;
}) {
  const t = useI18n();
  const hint = notOwner ?? (blocked ? t("taskBlockedWorkflowGone") : undefined);
  // 点不动的原因:不是主人、跑不起来(工作流删了)优先;否则是任务停着。「运行中」由按钮上的字自己说。
  const runBlockedBy = hint ?? (!enabled ? t("taskRunNeedsEnabled") : undefined);
  return (
    <div className="flex shrink-0 items-center gap-1.5">
      <Hint disabledReason={runBlockedBy}>
        <Button variant="outline" disabled={!enabled || blocked || !!notOwner} loading={running} onClick={onRun}>
          <Play size={13} /> {running ? t("runStatus_running") : t("runNow")}
        </Button>
      </Hint>
      {/* 说明挂在整个标签上:开关被禁用时自己收不到悬停。 */}
      <Hint label={hint}>
      <label className="inline-flex h-10 cursor-pointer select-none items-center gap-2 rounded-md border border-border px-3 text-ui-sm text-muted-foreground has-[:disabled]:cursor-not-allowed">
        <span>{enabled ? t("pluginOn") : t("pluginOff")}</span>
        {/* 跑不起来时**打不开,但关得掉** —— 万一它还开着(不变式成立之前留下的),得能停下它。 */}
        <Switch
          checked={enabled}
          disabled={!!notOwner || (blocked && !enabled)}
          aria-label={enabled ? t("pluginOn") : t("pluginOff")}
          onCheckedChange={onToggle}
        />
      </label>
      </Hint>
    </div>
  );
}
