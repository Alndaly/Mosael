import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { getWorkflowLibrary, type WorkflowFile } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { OverChromeModals } from "@/components/ui/overChromeModal";
import { Hint } from "@/components/ui/tooltip";
import { refreshConnectionCatalog } from "@/features/plugins/pluginCaches";
import { FormsUpgradeDialog } from "@/features/plugins/WorkflowFormsUpgrade";
import type { FormsLock } from "@/features/plugins/workflowAppForm";
import { PanelNote } from "@/features/plugins/workbench/workbenchParts";
import type { WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";

/**
 * 画布上这张的表单这一版**不能改**(`formsLock`:上一版的,或更新版插件写的)。工作台的「表单」页签只摆这一块,不摆编辑器、
 * 「结果取自」—— 照「没有表单」写进画布再一存盘,作者的表单就永久没了(PLG-1;插件那一侧也拒)。和网页版工作流库一致:
 * 上一版的给「查看并升级」(同一个弹窗,整台确认一次);更新版的说升级 Mosael。
 *
 * 升级改的是那台机器上的**文件**,画布上开着的还是读进来时那一份:升级完要在 ComfyUI 里关掉这张、重新打开才看得到表单;
 * 画布上有没存的改动、或者还没存过的,先不让升级(重新打开会丢掉没存的改动,存一下又把旧格式写回去)。
 */
export function FormsLocked({ target, lock, path, canvasModified }: {
  target: WorkbenchTarget;
  lock: FormsLock;
  /** 画布开的是哪张(存过的路径;新建没存的是空串) */
  path: string;
  canvasModified: boolean;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [workflows, setWorkflows] = React.useState<WorkflowFile[] | null>(null);
  const [done, setDone] = React.useState(false);
  const open = useMutation({
    mutationFn: () => getWorkflowLibrary(target.instanceId, target.workspaceId),
    onSuccess: (library) => setWorkflows(library.workflows ?? []),
  });
  if (!lock.upgradable) {
    return (
      <PanelNote tone="warning">
        <span data-forms-locked="newer">{t("workbenchFormsNewer").replace("{version}", lock.version || "?")}</span>
      </PanelNote>
    );
  }
  const blocked = !path ? t("workbenchFormsUpgradeSaveFirst") : canvasModified ? t("workbenchFormsUpgradeUnsaved") : "";
  const button = (
    <Button variant="outline" size="xs" disabled={Boolean(blocked)} loading={open.isPending} onClick={() => open.mutate()}
            data-forms-locked-upgrade="">
      {t("workflowFormsUpgradeOpen")}
    </Button>
  );
  return (
    <div className="grid min-w-0 gap-2">
      <PanelNote tone="warning" action={blocked ? <Hint label={blocked}><span>{button}</span></Hint> : button}>
        <span data-forms-locked="old">{t("workbenchFormsOld")}</span>
      </PanelNote>
      {done && <PanelNote><span data-forms-locked-done="">{t("workbenchFormsUpgraded")}</span></PanelNote>}
      {open.isError && <PanelNote tone="error">{errorText(open.error)}</PanelNote>}
      {workflows && (
        //: 弹窗压在外壳之上、请画布让开(不然中间被画布盖着、两边被外壳盖着,见 overChromeModal)
        <OverChromeModals.Provider value>
          <FormsUpgradeDialog
            instance={{ id: target.instanceId, name: target.instanceName }}
            workflows={workflows}
            onClose={() => setWorkflows(null)}
            onDone={() => {
              setDone(true);
              void qc.invalidateQueries({ queryKey: ["workflow-library", target.instanceId] });
              void refreshConnectionCatalog(qc, target.instanceId);
            }}
          />
        </OverChromeModals.Provider>
      )}
    </div>
  );
}
