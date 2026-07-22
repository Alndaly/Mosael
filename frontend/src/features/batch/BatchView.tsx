import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, Layers, Loader2, Plus, Trash2 } from "lucide-react";

import {
  createBatch,
  deleteBatch,
  listBatches,
  listWorkflows,
  type Batch,
  type BatchItem,
  type Workflow,
  type WorkflowGraph,
  type Workspace,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SettingsBlock, SettingsGroup, SettingsRow } from "@/features/settings/ui";
import { cn } from "@/lib/utils";

const ACTIVE = new Set(["queued", "running"]);

/** 批量页(计划 §13 批量混剪):同一工作流 × N 组参数,逐项跑、聚合看。 */
export function BatchView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState(false);
  const [deleting, setDeleting] = React.useState<Batch | null>(null);

  // 通知/任务中心深链(mibu:open-* 事件通道):直接选中那条批量记录。
  React.useEffect(() => {
    const onOpenBatch = (event: Event) => {
      const id = (event as CustomEvent<string>).detail;
      if (typeof id === "string" && id) setSelectedId(id);
    };
    window.addEventListener("mibu:open-batch", onOpenBatch);
    return () => window.removeEventListener("mibu:open-batch", onOpenBatch);
  }, []);

  const batches = useQuery({
    queryKey: ["batches", workspace.id],
    queryFn: () => listBatches(workspace.id),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((batch) => ACTIVE.has(batch.status)) ? 2000 : false,
    refetchOnWindowFocus: true,
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["batches", workspace.id] });

  const remove = useMutation({
    mutationFn: (id: string) => deleteBatch(id),
    onSuccess: () => {
      refresh();
    },
    // Closed in onSettled, not onSuccess: a failed request used to leave the dialog
    // open with its confirm button re-enabled, so repeated clicks fired repeated
    // requests. The global fallback still reports the error.
    onSettled: () => {
      setDeleting(null);
    },
  });

  const selected = (batches.data ?? []).find((batch) => batch.id === selectedId) ?? (batches.data ?? [])[0] ?? null;

  const createDialog = (
    <CreateBatchDialog
      open={creating}
      workspace={workspace}
      onClose={() => setCreating(false)}
      onCreated={(batch) => {
        setCreating(false);
        setSelectedId(batch.id);
        refresh();
      }}
    />
  );

  if (batches.isSuccess && (batches.data ?? []).length === 0) {
    return (
      <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-2.5 [&>*]:shrink-0">
        <EmptyState
          icon={<Layers size={22} />}
          title={t("batchEmptyTitle")}
          body={t("batchEmptyBody")}
          action={
            <Button onClick={() => setCreating(true)}>
              <Plus size={15} /> {t("batchCreate")}
            </Button>
          }
        />
        {createDialog}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-2.5 [&>*]:shrink-0">
      <div className="grid min-h-0 flex-1 grid-cols-[260px_minmax(0,1fr)] gap-1.5 max-[880px]:grid-cols-[minmax(0,1fr)] max-[880px]:grid-rows-[auto_minmax(0,1fr)]">
        <aside className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] grid grid-rows-[auto_minmax(0,1fr)] max-[880px]:flex max-[880px]:items-center max-[880px]:gap-1.5 max-[880px]:px-1.5 max-[880px]:py-[5px] max-[880px]:[&>div:first-child]:contents">
          <div className="flex min-h-[38px] items-center justify-between border-b border-border px-2.5 [&_h2]:m-0 [&_h2]:text-[11px] [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">
            <h2>{t("batchListTitle")}</h2>
            <Button variant="outline" size="sm" onClick={() => setCreating(true)}>
              <Plus size={13} /> {t("batchCreate")}
            </Button>
          </div>
          <div className="grid content-start gap-1 overflow-y-auto p-1.5 [&:has(>.empty-inline:only-child)]:content-stretch max-[880px]:order-1 max-[880px]:flex max-[880px]:min-w-0 max-[880px]:flex-1 max-[880px]:items-center max-[880px]:gap-1.5 max-[880px]:overflow-x-auto max-[880px]:p-0">
            {(batches.data ?? []).map((batch) => {
              const done = (batch.items ?? []).filter((item) => !ACTIVE.has(item.status) && item.status !== "pending").length;
              return (
                <ContextMenu key={batch.id}>
                  <ContextMenuTrigger asChild>
                    <button
                      type="button"
                      className={cn("flex cursor-pointer items-center gap-[9px] rounded-md border-0 bg-transparent px-2 py-1.5 text-left transition-colors duration-100 hover:bg-muted max-[880px]:shrink-0 max-[880px]:py-1", selected?.id === batch.id && "bg-accent hover:bg-accent")}
                      onClick={() => setSelectedId(batch.id)}
                    >
                      <span className={cn("h-[7px] w-[7px] shrink-0 rounded-full bg-border-strong", ACTIVE.has(batch.status) && "bg-[#22c55e]")} />
                      <span className="min-w-0 [&_small]:text-[11px] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:truncate [&_strong]:text-[12.5px] [&_strong]:font-semibold max-[880px]:[&_small]:hidden">
                        <strong>{batch.name}</strong>
                        <small>
                          {done}/{(batch.items ?? []).length} · {t(`batchStatus_${batch.status}` as never)}
                        </small>
                      </span>
                    </button>
                  </ContextMenuTrigger>
                  <ContextMenuContent>
                    <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => setDeleting(batch)}>
                      <Trash2 /> {t("delete")}
                    </ContextMenuItem>
                  </ContextMenuContent>
                </ContextMenu>
              );
            })}
          </div>
        </aside>
        <div className="grid min-w-0 overflow-y-auto">
          {selected ? (
            <BatchDetail key={selected.id} batch={selected} workspaceId={workspace.id} onDelete={() => setDeleting(selected)} />
          ) : (
            <EmptyState icon={<Layers size={22} />} title={t("pickDetailTitle")} body={t("pickDetailBody")} />
          )}
        </div>
      </div>
      {createDialog}
      <ConfirmDialog
        open={deleting !== null}
        title={t("deleteConfirmTitle")}
        body={t("batchDeleteBody")}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  );
}

function BatchDetail({
  batch,
  workspaceId,
  onDelete,
}: {
  batch: Batch;
  workspaceId: string;
  onDelete: () => void;
}) {
  const t = useI18n();
  const workflows = useQuery({ queryKey: ["workflows", workspaceId], queryFn: () => listWorkflows(workspaceId) });
  const workflow = (workflows.data ?? []).find((item) => item.id === batch.workflow_id) ?? null;
  const succeeded = (batch.items ?? []).filter((item) => item.status === "succeeded").length;
  const failed = (batch.items ?? []).filter((item) => item.status === "failed").length;

  return (
    <div className="grid w-full content-start gap-3 px-0.5 pb-4 pt-0.5">
      <SettingsGroup
        title={batch.name}
        description={`${t("wfBoundWorkflow")}: ${workflow?.name ?? batch.workflow_id} · ${succeeded}/${(batch.items ?? []).length} ${t("batchSucceededShort")}${failed ? ` · ${failed} ${t("batchFailedShort")}` : ""}`}
        actions={
          <div className="flex items-center gap-1.5">
            {ACTIVE.has(batch.status) && <Loader2 size={14} className="spin" />}
            <Button size="sm" variant="outline" className="hover:border-[color-mix(in_oklab,var(--destructive)_45%,var(--border))] hover:text-destructive" onClick={onDelete}>
              <Trash2 size={13} /> {t("delete")}
            </Button>
          </div>
        }
      >
        <SettingsRow label={t("batchProgress")} description={t("batchProgressDesc")}>
          <div className="flex w-60 items-center gap-2 [&_.timecode]:text-[11px] [&_.timecode]:text-muted-foreground">
            <Progress value={Math.round(batch.progress * 100)} />
            <span className="timecode">{Math.round(batch.progress * 100)}%</span>
          </div>
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title={t("batchItems")} description={t("batchItemsDesc")}>
        <SettingsBlock>
          {(batch.items ?? []).map((item) => (
            <BatchItemRow key={item.index} item={item} />
          ))}
        </SettingsBlock>
      </SettingsGroup>
    </div>
  );
}

function BatchItemRow({ item }: { item: BatchItem }) {
  const t = useI18n();
  const paramsSummary = Object.entries(item.params ?? {})
    .map(([key, value]) => `${key}=${String(value)}`)
    .join("  ") || "—";
  return (
    <div className="flex items-center gap-2 border-b border-border px-2.5 py-1.5 text-[12.5px] last:border-b-0">
      <span className="timecode w-[34px] flex-none text-[11px] text-muted-foreground">#{item.index + 1}</span>
      <span className="min-w-0 flex-1 truncate" title={paramsSummary}>
        {paramsSummary}
      </span>
      <span className="inline-flex flex-none items-center gap-[5px] text-[11.5px] text-muted-foreground">
        {item.status === "succeeded" ? (
          <CheckCircle2 size={13} className="text-[#16a34a]" />
        ) : item.status === "failed" ? (
          <CircleAlert size={13} className="text-destructive" />
        ) : ACTIVE.has(item.status) ? (
          <Loader2 size={13} className="spin" />
        ) : null}
        {t(`batchStatus_${item.status}` as never)}
      </span>
      {item.error && (
        <span className="max-w-[260px] truncate text-[11px] text-destructive" title={item.error}>
          {item.error}
        </span>
      )}
    </div>
  );
}

/** 新建批量:选工作流 → 按 start 参数生成表格列,一行 = 一次运行。 */
function CreateBatchDialog({
  open,
  workspace,
  onClose,
  onCreated,
}: {
  open: boolean;
  workspace: Workspace;
  onClose: () => void;
  onCreated: (batch: Batch) => void;
}) {
  const t = useI18n();
  const [name, setName] = React.useState("");
  const [workflowId, setWorkflowId] = React.useState<string | null>(null);
  const [rows, setRows] = React.useState<Array<Record<string, string>>>([{}]);

  const workflows = useQuery({
    queryKey: ["workflows", workspace.id],
    queryFn: () => listWorkflows(workspace.id),
    enabled: open,
  });
  const selectedWorkflow = (workflows.data ?? []).find((workflow: Workflow) => workflow.id === workflowId) ?? null;
  const paramKeys = React.useMemo(() => {
    if (!selectedWorkflow) return [] as string[];
    const graph = selectedWorkflow.graph as unknown as WorkflowGraph;
    const start = (graph.nodes ?? []).find((node) => node.type === "start");
    return Object.keys(((start?.config as { params?: Record<string, unknown> })?.params ?? {}) as object);
  }, [selectedWorkflow]);

  const create = useMutation({
    mutationFn: () =>
      createBatch({
        workspace_id: workspace.id,
        workflow_id: workflowId!,
        name: name.trim() || `${selectedWorkflow?.name ?? ""} × ${rows.length}`,
        params_list: rows,
      }),
    onSuccess: (batch) => {
      setName("");
      setRows([{}]);
      onCreated(batch);
    },
  });

  return (
    <ModalShell open={open} onOpenChange={(next) => !next && onClose()} title={t("batchCreate")}>
      <div className="grid min-w-0 gap-2.5 [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-panel [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
        <label className="wf-field">
          <span>{t("batchNameLabel")}</span>
          <Input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="wf-field">
          <span>{t("wfBoundWorkflow")}</span>
          <Select
            value={workflowId ?? ""}
            onValueChange={(value) => {
              setWorkflowId(value);
              setRows([{}]);
            }}
          >
            <SelectTrigger>
              <SelectValue placeholder={t("wfPickWorkflow")} />
            </SelectTrigger>
            <SelectContent>
              {(workflows.data ?? []).map((workflow: Workflow) => (
                <SelectItem key={workflow.id} value={workflow.id}>
                  {workflow.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        {workflowId && (
          <div className="wf-field">
            <span>
              {t("batchRows")} · {rows.length}
            </span>
            <div className="grid max-h-[260px] gap-1.5 overflow-y-auto">
              {rows.map((row, rowIndex) => (
                <div className="flex items-center gap-1.5" key={rowIndex}>
                  <span className="timecode w-[26px] flex-none text-[10.5px] text-muted-foreground">#{rowIndex + 1}</span>
                  {paramKeys.length > 0 ? (
                    paramKeys.map((key) => (
                      <Input
                        key={key}
                        placeholder={key}
                        value={row[key] ?? ""}
                        onChange={(event) =>
                          setRows((current) =>
                            current.map((item, index) =>
                              index === rowIndex ? { ...item, [key]: event.target.value } : item,
                            ),
                          )
                        }
                      />
                    ))
                  ) : (
                    <span className="flex-1 text-xs text-muted-foreground">{t("batchNoParams")}</span>
                  )}
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("delete")}
                    disabled={rows.length <= 1}
                    onClick={() => setRows((current) => current.filter((_item, index) => index !== rowIndex))}
                  >
                    <Trash2 size={13} />
                  </Button>
                </div>
              ))}
            </div>
            <Button variant="outline" size="sm" onClick={() => setRows((current) => [...current, {}])}>
              <Plus size={13} /> {t("batchAddRow")}
            </Button>
          </div>
        )}
        <div className="mt-1 flex justify-end gap-1.5">
          <Button variant="outline" size="sm" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button size="sm" disabled={!workflowId || rows.length === 0 || create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? <Loader2 size={13} className="spin" /> : <Layers size={13} />} {t("batchStart")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}
