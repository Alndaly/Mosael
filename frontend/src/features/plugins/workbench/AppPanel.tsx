import React from "react";
import { useMutation } from "@tanstack/react-query";
import { RefreshCcw } from "lucide-react";

import type { WorkflowApp } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { LoadingState } from "@/components/layout/LoadingState";
import { Button } from "@/components/ui/button";
import { AppFormEditor } from "@/features/plugins/WorkflowAppEditor";
import { initialDraft, sameDraft, type AppDraft } from "@/features/plugins/workflowAppForm";
import { readCanvasApp, writeCanvasApp } from "@/features/plugins/workbench/canvasMarks";
import { PanelNote } from "@/features/plugins/workbench/workbenchParts";
import { WorkbenchCallError, type WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";

/**
 * 工作台的「应用」面板(ADR 0038 §2、§8):工作流库里那个应用表单编辑器,绑在**画布上现在这张**上。读:经桥导出画布(含没存的),
 * 插件列出全部能填的项和画布上的标记;写:插件算出要改的那几处标记,经桥改画布上的节点 —— 不写文件,存盘是 ComfyUI 自己的保存
 * (顶栏的「保存」或在画布里 Ctrl+S),和用户在 ComfyUI 里改别的东西是同一次保存。
 */
export function AppPanel({ target, canExport, canMark }: { target: WorkbenchTarget; canExport: boolean; canMark: boolean }) {
  const t = useI18n();
  const [data, setData] = React.useState<WorkflowApp | null>(null);
  const [draft, setDraft] = React.useState<AppDraft | null>(null);
  const [base, setBase] = React.useState<AppDraft | null>(null);
  const [written, setWritten] = React.useState(false);
  const read = useMutation({
    mutationFn: () => readCanvasApp(target.instanceId),
    onSuccess: ({ data: next }) => {
      const fresh = initialDraft(next);
      setData(next);
      setDraft(fresh);
      setBase(fresh);
    },
  });
  const write = useMutation({
    mutationFn: (next: AppDraft) => writeCanvasApp(target.instanceId, next),
    onSuccess: (_done, next) => {
      setBase(next);
      setWritten(true);
    },
  });
  const load = read.mutate;
  React.useEffect(() => {
    if (canExport && canMark) load();
  }, [canExport, canMark, load]);

  if (!canExport || !canMark) {
    return <PanelNote tone="warning">{t("workbenchUnsupported").replace("{what}", t(canExport ? "workbenchCapMarks" : "workbenchCapExport"))}</PanelNote>;
  }
  const failure = read.error ?? write.error;
  const dirty = Boolean(draft && base && !sameDraft(draft, base));
  return (
    <div className="grid gap-3">
      <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("workbenchAppHint")}</p>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button variant="outline" size="xs" loading={read.isPending} onClick={() => {
          setWritten(false);
          load();
        }}>
          <RefreshCcw size={12} />
          {t("workbenchAppReload")}
        </Button>
        <Button size="xs" disabled={!draft || !dirty} loading={write.isPending} onClick={() => draft && write.mutate(draft)}>
          {t("workbenchAppWrite")}
        </Button>
      </div>
      {written && !dirty && <PanelNote>{t("workbenchAppWritten")}</PanelNote>}
      {failure && (
        <PanelNote tone="error">
          {failure instanceof WorkbenchCallError ? t("workbenchCallFailed").replace("{why}", failure.message) : errorText(failure)}
        </PanelNote>
      )}
      {read.isPending && !data ? (
        <LoadingState label={t("workflowAppLoading")} className="h-auto py-8" />
      ) : data && draft ? (
        <AppFormEditor instance={{ id: target.instanceId }} data={data} draft={draft} stacked
                       onChange={(next) => {
                         setWritten(false);
                         setDraft(next);
                       }} />
      ) : null}
    </div>
  );
}
