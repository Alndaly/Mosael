import React from "react";
import { useMutation } from "@tanstack/react-query";
import { RefreshCcw } from "lucide-react";

import type { WorkflowApp } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { LoadingState } from "@/components/layout/LoadingState";
import { Button } from "@/components/ui/button";
import { OverChromeModals } from "@/components/ui/overChromeModal";
import { AppFormEditor, AppHead } from "@/features/plugins/appForm/AppFormEditor";
import { ResultsSection } from "@/features/plugins/appForm/FormBuilder";
import { FormsBar } from "@/features/plugins/appForm/FormsBar";
import { NoForms } from "@/features/plugins/WorkflowAppEditor";
import {
  appendForm,
  blankForm,
  formsLock,
  initialDraft,
  replaceForm,
  sameDraft,
  toggleResult,
  untitled,
  type FormsDraft,
} from "@/features/plugins/workflowAppForm";
import { readCanvasApp, writeCanvasApp } from "@/features/plugins/workbench/canvasMarks";
import { FormsLocked } from "@/features/plugins/workbench/FormsLocked";
import { PanelNote } from "@/features/plugins/workbench/workbenchParts";
import { WorkbenchCallError, type WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";

/**
 * 工作台的「表单」页签(ADR 0038 §2、§8,ADR 0045 §7):工作流库里那个表单编辑器,绑在**画布上现在这张**上,窄版(挑项 / 表单 /
 * 预览三个标签)。顶上「结果取自」(按工作流记)和表单那一排(切换、新表单、复制、删除),下面是选中那张的标题、说明和编辑器。
 * 读:经桥导出画布(含没存的),插件列出全部能填的项和画布上的每张表单;写:插件算出要改的那几处标记,经桥改画布上的节点 ——
 * 不写文件,存盘是 ComfyUI 自己的保存(顶栏的「保存」或在画布里 Ctrl+S),和用户在 ComfyUI 里改别的东西是同一次保存。
 * 写完重新读一遍画布:新表单的 id 是插件起的,下次再写带着它,不会又起一个。
 */
export function AppPanel({ target, workflowKey, path = "", canvasModified, canExport, canMark }: {
  target: WorkbenchTarget;
  /** 画布上现在开着的那张认哪个 key(轮询报的;改名、第一次存盘跟着变):草稿只写给它,写的那一刻画布上换了一张就不写 */
  workflowKey: string;
  /** 画布开的是哪张(存过的路径;新建没存的是空串):插件据此说出每张表单的模型 id 和工具名,删之前数在用的几处 */
  path?: string;
  /** 画布上这张有没存的改动(桥报的 `modified`):同步过之后一存盘,「还没保存」那句就收起来 */
  canvasModified: boolean;
  canExport: boolean;
  canMark: boolean;
}) {
  const t = useI18n();
  const [data, setData] = React.useState<WorkflowApp | null>(null);
  const [draft, setDraft] = React.useState<FormsDraft | null>(null);
  const [base, setBase] = React.useState<FormsDraft | null>(null);
  const [selected, setSelected] = React.useState("");
  const [written, setWritten] = React.useState(false);
  const read = useMutation({
    mutationFn: () => readCanvasApp(target.instanceId, path),
    onSuccess: ({ data: next }) => {
      const fresh = initialDraft(next);
      setData(next);
      setDraft(fresh);
      setBase(fresh);
      //: 读回来之后还停在原来那张(按位置认:新表单写进去之后有了 id,它的 key 换了)
      setSelected((was) => {
        const at = draft?.forms.findIndex((one) => one.key === was) ?? -1;
        return fresh.forms[at]?.key ?? fresh.forms.find((one) => one.key === was)?.key ?? fresh.forms[0]?.key ?? "";
      });
    },
  });
  const write = useMutation({
    mutationFn: (next: FormsDraft) => writeCanvasApp(target.instanceId, workflowKey, next),
    onSuccess: () => {
      setWritten(true);
      read.mutate();
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
  const change = (next: FormsDraft) => {
    setWritten(false);
    setDraft(next);
  };
  const dirty = Boolean(draft && base && !sameDraft(draft, base));
  const nameless = draft ? untitled(draft).length : 0;
  const current = draft?.forms.find((one) => one.key === selected) ?? null;
  //: 上一版 / 更新版插件写的表单:这一版读成「没有表单」,照空草稿写进画布再一存盘就把它们抹掉了 —— 只说清楚、不给写
  const lock = data ? formsLock(data) : null;
  //: 一屏一个视觉焦点(维护者 2026-10-09):还没有表单、也没改什么时,焦点是空状态里那颗「新表单」—— 那几行怎么同步、怎么存的说明
  //: 和「同步到画布」都还用不上,不摆;有了表单(或者刚删光、还没同步)再出来。「同步到画布」只在点得了时是实心主按钮
  const authoring = Boolean(draft && (draft.forms.length > 0 || dirty));
  //: 点得了才是实心(有改动、每张都起了标题):点不了的实心主按钮也在抢焦点 —— 那时焦点是起标题、挑项
  const canWrite = Boolean(draft) && dirty && nameless === 0;
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-3">
      {authoring && <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground" data-app-hint="">{t("workbenchAppHint")}</p>}
      <div className="flex flex-wrap items-center justify-end gap-2">
        {dirty && (
          <span role="status" data-app-dirty="" className="mr-auto inline-flex items-center gap-1.5 text-ui-xs font-medium text-warning">
            <span aria-hidden className="size-1.5 rounded-full bg-warning" />
            {nameless > 0 ? t("workflowFormsUntitled").replace("{n}", String(nameless)) : t("workbenchAppDirty")}
          </span>
        )}
        <Button variant="outline" size="xs" loading={read.isPending && !write.isPending} onClick={() => {
          setWritten(false);
          load();
        }}>
          <RefreshCcw size={12} />
          {t("workbenchAppReload")}
        </Button>
        {!lock && authoring && (
          <Button size="xs" variant={canWrite ? "default" : "outline"} disabled={!canWrite}
                  loading={write.isPending} onClick={() => draft && write.mutate(draft)}>
            {t("workbenchAppWrite")}
          </Button>
        )}
      </div>
      {written && !dirty && canvasModified && <PanelNote>{t("workbenchAppWritten")}</PanelNote>}
      {failure && (
        <PanelNote tone="error">
          {failure instanceof WorkbenchCallError ? t("workbenchCallFailed").replace("{why}", failure.message) : errorText(failure)}
        </PanelNote>
      )}
      {read.isPending && !data ? (
        <LoadingState label={t("workflowAppLoading")} className="h-auto min-h-0 flex-1" />
      ) : data && lock ? (
        <FormsLocked target={target} lock={lock} path={path} canvasModified={canvasModified} />
      ) : data && draft ? (
        <>
          <ResultsSection outputs={data.outputs ?? []} results={draft.results} onToggle={(node) => change(toggleResult(draft, node))} />
          {/* 删表单的确认框压在外壳之上、请画布让开(不然中间被画布盖着、两边被外壳盖着,见 overChromeModal) */}
          <OverChromeModals.Provider value>
            <FormsBar data={data} draft={draft} selected={selected} instanceId={target.instanceId} workspaceId={target.workspaceId}
                      onSelect={setSelected} onChange={(next, select) => {
                        change(next);
                        setSelected(select);
                      }} />
          </OverChromeModals.Provider>
          {current ? (
            <>
              <AppHead draft={current} onChange={(next) => change(replaceForm(draft, current.key, next))} />
              <AppFormEditor instance={{ id: target.instanceId }} data={data} draft={current} layout="narrow"
                             onChange={(next) => change(replaceForm(draft, current.key, next))} />
            </>
          ) : (
            <NoForms onNew={() => {
              const added = blankForm();
              change(appendForm(draft, added));
              setSelected(added.key);
            }} />
          )}
        </>
      ) : null}
    </div>
  );
}
