import React from "react";
import { useMutation } from "@tanstack/react-query";
import { CircleCheck, TriangleAlert } from "lucide-react";

import { upgradeWorkflowMarks, type PluginInstance, type WorkflowFile, type WorkflowUpgradeResult } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";

/**
 * 上一版格式的表单(ADR 0045 §7):1.21 起插件不读第 1 版的表单标记(读的一侧不留认旧版的分支),那些工作流的表单入口在升级之前
 * 都不在 —— 指着它们的格子、会话说「到工作流库里升级」。工作流库顶上一条横幅说有几张,「查看并升级」打开弹窗:列出这台服务器上
 * 要改的文件、写明只改每张里 Mosael 的标记、ComfyUI 里刚改过的那张会跳过;**确认一次,整台改完**,报改了几张、跳过几张。
 * 每个连接确认一次(文件在各自的服务器上)。
 */
export function upgradableWorkflows(workflows: readonly WorkflowFile[]): WorkflowFile[] {
  return workflows.filter((one) => one.app?.upgradable);
}

export function FormsUpgradeBanner({ count, onOpen }: { count: number; onOpen: () => void }) {
  const t = useI18n();
  return (
    <div role="status" data-forms-upgrade-banner=""
         className="flex min-w-0 flex-wrap items-center gap-2 rounded-lg border border-warning/40 bg-panel px-3 py-2 text-ui-sm">
      <TriangleAlert size={14} aria-hidden className="shrink-0 text-warning" />
      <span className="min-w-0 flex-1 basis-60">{t("workflowFormsUpgradeBanner").replace("{n}", String(count))}</span>
      <Button variant="outline" size="sm" onClick={onOpen}>{t("workflowFormsUpgradeOpen")}</Button>
    </div>
  );
}

export function FormsUpgradeDialog({ instance, workflows, onClose, onDone }: {
  instance: PluginInstance;
  workflows: readonly WorkflowFile[];
  onClose: () => void;
  /** 改成了:工作流库、生成选项重新问(宿主已经让这个连接的目录重拉过) */
  onDone: () => void;
}) {
  const t = useI18n();
  //: 打开时那一份:升级完列表会刷新,弹窗里照旧说这次改的是哪几张
  const [targets] = React.useState(() => upgradableWorkflows(workflows));
  const upgrade = useMutation({
    mutationFn: () => upgradeWorkflowMarks(instance.id, targets.map((one) => ({ path: one.path, modified: one.modified }))),
    onSuccess: (result) => {
      if ((result.upgraded ?? []).length > 0) onDone();
    },
  });
  const result = upgrade.data;
  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && !upgrade.isPending && onClose()}
      title={t("workflowFormsUpgradeTitle").replace("{server}", instance.name)}
      className="w-[min(640px,calc(100vw-32px))]"
      footer={result ? (
        <Button onClick={onClose}>{t("close")}</Button>
      ) : (
        <>
          <Button variant="ghost" disabled={upgrade.isPending} onClick={onClose}>{t("cancel")}</Button>
          <Button loading={upgrade.isPending} disabled={targets.length === 0} onClick={() => upgrade.mutate()}
                  data-forms-upgrade-confirm="">
            {t("workflowFormsUpgradeConfirm").replace("{n}", String(targets.length))}
          </Button>
        </>
      )}
    >
      <div className="grid min-w-0 gap-3 text-ui-sm" data-forms-upgrade="">
        {result ? <UpgradeOutcome result={result} /> : (
          <>
            <p className="m-0 leading-relaxed text-foreground">{t("workflowFormsUpgradeBody")}</p>
            <ul className="m-0 grid max-h-72 list-none gap-1 overflow-y-auto rounded-lg border border-border p-2 font-mono text-ui-xs"
                aria-label={t("workflowFormsUpgradeFiles")}>
              {targets.map((one) => <li key={one.path} className="break-all">{one.path}</li>)}
            </ul>
          </>
        )}
        {upgrade.error && <p role="alert" className="m-0 text-destructive">{errorText(upgrade.error)}</p>}
      </div>
    </ModalShell>
  );
}

/** 改完说了什么:改成了几张、刚改过而跳过的、不在了的、没改成的(带原因)。 */
function UpgradeOutcome({ result }: { result: WorkflowUpgradeResult }) {
  const t = useI18n();
  const join = (paths: string[]) => paths.join(t("listSeparator"));
  const stale = result.stale ?? [];
  const gone = result.gone ?? [];
  const failed = result.failed ?? [];
  return (
    <div className="grid gap-2" role="status" data-forms-upgrade-result="">
      <p className="m-0 flex items-center gap-2 font-medium text-foreground">
        <CircleCheck size={14} aria-hidden className="shrink-0 text-success" />
        {t("workflowFormsUpgraded").replace("{n}", String((result.upgraded ?? []).length))}
      </p>
      {stale.length > 0 && (
        <p className="m-0 text-warning">{t("workflowFormsUpgradeStale").replace("{n}", String(stale.length)).replace("{paths}", join(stale))}</p>
      )}
      {gone.length > 0 && (
        <p className="m-0 text-muted-foreground">{t("workflowFormsUpgradeGone").replace("{paths}", join(gone))}</p>
      )}
      {failed.map((one) => (
        <p key={one.path} className="m-0 break-words text-destructive">
          {t("workflowFormsUpgradeFailed").replace("{path}", one.path).replace("{why}", one.reason ?? "")}
        </p>
      ))}
    </div>
  );
}
