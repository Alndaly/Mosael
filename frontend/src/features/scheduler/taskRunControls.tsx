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

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";

export function TaskRunControls({
  enabled,
  blocked,
  running,
  onRun,
  onToggle,
}: {
  enabled: boolean;
  /** 跑不起来(绑的工作流已删除)。 */
  blocked: boolean;
  running: boolean;
  onRun: () => void;
  onToggle: (enabled: boolean) => void;
}) {
  const t = useI18n();
  // 说明挂在外层:被禁用的按钮不接收指针事件,自己身上的 title 悬停时出不来。
  const hint = blocked ? t("taskBlockedWorkflowGone") : undefined;
  return (
    <div className="flex shrink-0 items-center gap-1.5">
      <span title={hint}>
        <Button variant="outline" disabled={!enabled || blocked} loading={running} onClick={onRun}>
          <Play size={13} /> {t("runNow")}
        </Button>
      </span>
      <label
        title={hint}
        className="inline-flex h-10 cursor-pointer select-none items-center gap-2 rounded-md border border-border px-3 text-ui-sm text-muted-foreground has-[:disabled]:cursor-not-allowed"
      >
        <span>{enabled ? t("pluginOn") : t("pluginOff")}</span>
        {/* 跑不起来时**打不开,但关得掉** —— 万一它还开着(不变式成立之前留下的),得能停下它。 */}
        <Switch
          checked={enabled}
          disabled={blocked && !enabled}
          aria-label={enabled ? t("pluginOn") : t("pluginOff")}
          onCheckedChange={onToggle}
        />
      </label>
    </div>
  );
}
