import React from "react";

import { useI18n } from "@/app/preferences";
import { ModalShell, ModalSubmit } from "@/components/app/modals";
import { RunParamsForm } from "@/features/workflows/RunParamsForm";
import { formValuesFrom, missingRequired, runParamsFrom, startParamsOf, type StartParamSpec } from "@/features/workflows/runParams";

/**
 * 开始节点里勾了「必填」又没有默认值的参数,点运行时**当场问**:画布上写的是「运行时填」,此前点运行发出去的参数
 * 永远是 `{}`,画布检查又因为它空着把运行键灰掉 —— 那一格写着的事做不到。现在点运行先弹这一张,填好了只带给这一次
 * (不改工作流里的默认值),和定时任务带参数同一套表单、同一套校验(见 runParams)。
 */

/** 这张图点运行之前要不要先问:有必填又没有默认值的参数就要。 */
export function needsRunParams(graph: unknown): boolean {
  const specs = startParamsOf(graph);
  return missingRequired(specs, formValuesFrom(specs, {})).length > 0;
}

export function RunParamsDialog({
  graph,
  open,
  onOpenChange,
  onRun,
  running,
}: {
  graph: unknown;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 填好的这一次的参数(只有填了的那几项)。 */
  onRun: (params: Record<string, unknown>) => void;
  running: boolean;
}) {
  const t = useI18n();
  const specs: StartParamSpec[] = React.useMemo(() => startParamsOf(graph), [graph]);
  const [values, setValues] = React.useState<Record<string, string>>(() => formValuesFrom(specs, {}));
  const [attempted, setAttempted] = React.useState(false);
  //: 每次打开都从头填:上一次填的属于上一次。
  React.useEffect(() => {
    if (!open) return;
    setValues(formValuesFrom(specs, {}));
    setAttempted(false);
  }, [open, specs]);
  const missing = missingRequired(specs, values);
  const submit = () => {
    setAttempted(true);
    if (missing.length === 0) onRun(runParamsFrom(specs, values));
  };
  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={t("wfRunParamsTitle")}
      onSubmit={submit}
      footer={<ModalSubmit loading={running}>{t("wfRun")}</ModalSubmit>}
    >
      <div data-run-params-dialog="">
        <RunParamsForm
          specs={specs}
          values={values}
          onChange={setValues}
          showMissing={attempted}
          missing={missing}
          hint={t("wfRunParamsHint")}
        />
      </div>
    </ModalShell>
  );
}
