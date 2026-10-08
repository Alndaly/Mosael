import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Copy, FilePlus2, MoreHorizontal, Plus, Sparkles, Trash2, TriangleAlert } from "lucide-react";

import { getFormUsages, type WorkflowApp, type WorkflowFormUse } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { ActionMenu } from "@/components/app/ActionMenu";
import { ConfirmDialog } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import {
  MAX_FORMS,
  addRecommended,
  appendForm,
  blankForm,
  copyForm,
  removeForm,
  type FormDraft,
  type FormsDraft,
} from "@/features/plugins/workflowAppForm";
import { cn } from "@/lib/utils";

type Translate = ReturnType<typeof useI18n>;

/** 一张表单在列表里叫什么:标题,没起就是「未命名表单」(上一版改写过来、当初没起标题的那张)。 */
export function formName(form: FormDraft, t: Translate): string {
  return form.title.trim() || t("workflowFormUntitled");
}

/**
 * 一张工作流的几张表单(ADR 0045 §7):顶上一排(标题,没起的写「未命名表单」、标个提醒)+「新表单」(空白 / 按推荐先挑一版 /
 * 复制这张);选中的那张能复制、删除。下面是哪张的编辑器由调用方摆(工作流库的弹窗、工作台的表单页签同一个它)。
 *
 * **删表单**先确认,确认框里写出这个工作区里有几处在用它(画板、工作流、AI Studio 会话 —— 宿主按它的模型 id 和工具名数):删了
 * 之后那几处会说「这张表单已经没了」,不悄悄换成完整工作流。删的是草稿里的那张,保存之后才真的删;没存过的新表单直接删。
 */
export function FormsBar({
  data,
  draft,
  selected,
  instanceId,
  workspaceId,
  onSelect,
  onChange,
}: {
  data: WorkflowApp;
  draft: FormsDraft;
  /** 选中的那张(`FormDraft.key`);没有表单时是空串 */
  selected: string;
  instanceId: string;
  /** 数「这个工作区里有几处在用它」;不给就不数(只说保存之后才删) */
  workspaceId?: string;
  onSelect: (key: string) => void;
  /** 草稿变了;`select` 是变完之后该选中的那张(新加的、复制出来的、删了之后挨着的那张) */
  onChange: (next: FormsDraft, select: string) => void;
}) {
  const t = useI18n();
  const [deleting, setDeleting] = React.useState<FormDraft | null>(null);
  const current = draft.forms.find((one) => one.key === selected) ?? null;
  const full = draft.forms.length >= MAX_FORMS;
  const add = (form: FormDraft) => onChange(appendForm(draft, form), form.key);
  const newActions = [
    { label: t("workflowFormNewBlank"), icon: <FilePlus2 />, onSelect: () => add(blankForm()) },
    { label: t("workflowFormNewRecommended"), icon: <Sparkles />, onSelect: () => add(addRecommended(blankForm(), data)) },
    ...(current ? [{ label: t("workflowFormNewCopy").replace("{name}", formName(current, t)), icon: <Copy />, truncate: true,
                     onSelect: () => add(copyForm(current, t("workflowFormCopySuffix"))) }] : []),
  ];
  const remove = (form: FormDraft) => {
    const index = draft.forms.findIndex((one) => one.key === form.key);
    const next = removeForm(draft, form.key);
    onChange(next, next.forms[Math.min(index, next.forms.length - 1)]?.key ?? "");
  };

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2" data-forms-bar="">
      <div role="tablist" aria-label={t("workflowFormsBar")} className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
        {draft.forms.map((form) => {
          const on = form.key === selected;
          const named = Boolean(form.title.trim());
          return (
            <button
              key={form.key}
              type="button"
              role="tab"
              aria-selected={on}
              data-form-key={form.key}
              onClick={() => onSelect(form.key)}
              className={cn(
                "inline-flex h-8 max-w-56 min-w-0 items-center gap-1.5 rounded-full border px-3 text-ui-sm transition-colors",
                on ? "border-primary/60 bg-accent text-foreground" : "border-border text-muted-foreground hover:bg-secondary",
                !named && "italic",
              )}
            >
              {!named && <TriangleAlert size={12} aria-hidden className="shrink-0 text-warning" />}
              <Truncate>{formName(form, t)}</Truncate>
              {form.items.some((one) => one.problem) && (
                <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-warning" />
              )}
            </button>
          );
        })}
        <ActionMenu
          label={t("workflowFormNew")}
          align="start"
          actions={newActions.map((one) => ({
            ...one,
            disabled: full,
            description: full ? t("workflowFormsMax").replace("{n}", String(MAX_FORMS)) : undefined,
          }))}
          trigger={
            <Button variant="outline" size="sm" aria-haspopup="menu" data-forms-new="">
              <Plus size={14} />
              {t("workflowFormNew")}
            </Button>
          }
        />
      </div>
      {current && (
        <ActionMenu
          label={t("workflowFormActions").replace("{name}", formName(current, t))}
          actions={[
            { label: t("workflowFormNewCopy").replace("{name}", formName(current, t)), icon: <Copy />, truncate: true,
              disabled: full, description: full ? t("workflowFormsMax").replace("{n}", String(MAX_FORMS)) : undefined,
              onSelect: () => add(copyForm(current, t("workflowFormCopySuffix"))) },
            { label: t("workflowFormDelete"), icon: <Trash2 />, destructive: true, onSelect: () => setDeleting(current) },
          ]}
          trigger={
            <IconButton variant="ghost" size="icon-sm" aria-haspopup="menu"
                        label={t("workflowFormActions").replace("{name}", formName(current, t))}>
              <MoreHorizontal />
            </IconButton>
          }
        />
      )}
      {deleting && (
        <DeleteForm
          form={deleting}
          instanceId={instanceId}
          workspaceId={workspaceId}
          onCancel={() => setDeleting(null)}
          onConfirm={() => {
            remove(deleting);
            setDeleting(null);
          }}
        />
      )}
    </div>
  );
}

/** 删一张表单的确认框:存过的那张先数一下这个工作区里有几处在用它,一处一处列出来。 */
function DeleteForm({ form, instanceId, workspaceId, onCancel, onConfirm }: {
  form: FormDraft;
  instanceId: string;
  workspaceId?: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const t = useI18n();
  const counted = Boolean(workspaceId && form.id && (form.model || form.tool));
  const usages = useQuery({
    queryKey: ["form-usages", instanceId, workspaceId, form.model, form.tool],
    queryFn: () => getFormUsages(instanceId, { workspace_id: workspaceId ?? "", model: form.model, tool: form.tool }),
    enabled: counted,
    staleTime: 0,
  });
  const uses = usages.data?.uses ?? [];
  return (
    <ConfirmDialog
      open
      title={t("workflowFormDeleteTitle").replace("{name}", formName(form, t))}
      body={t("workflowFormDeleteBody")}
      confirmLabel={t("workflowFormDeleteConfirm")}
      pending={false}
      onCancel={onCancel}
      onConfirm={onConfirm}
    >
      {counted && (
        <div className="grid gap-1.5 text-ui-sm" data-form-usages="">
          {usages.isPending ? (
            <p className="m-0 text-muted-foreground">{t("workflowFormDeleteChecking")}</p>
          ) : usages.isError ? (
            <p className="m-0 text-destructive">{t("workflowFormDeleteCheckFailed")}</p>
          ) : uses.length === 0 ? (
            <p className="m-0 text-muted-foreground">{t("workflowFormDeleteUnused")}</p>
          ) : (
            <>
              <p className="m-0 font-medium text-foreground">{t("workflowFormDeleteInUse").replace("{n}", String(uses.length))}</p>
              <ul className="m-0 grid list-disc gap-0.5 pl-5 text-muted-foreground">
                {uses.map((one) => <li key={`${one.kind}:${one.id}`}>{usageLine(one, t)}</li>)}
              </ul>
            </>
          )}
        </div>
      )}
    </ConfirmDialog>
  );
}

function usageLine(use: WorkflowFormUse, t: Translate): string {
  const key = use.kind === "board" ? "workflowFormUse_board" : use.kind === "workflow" ? "workflowFormUse_workflow"
    : "workflowFormUse_session";
  return t(key).replace("{name}", use.name || use.id).replace("{n}", String(use.count ?? 1));
}
