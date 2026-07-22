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
      <div className="feature-view">
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
    <div className="feature-view">
      <div className="plugins-shell">
        <aside className="plugins-list panel">
          <div className="panel-head">
            <h2>{t("batchListTitle")}</h2>
            <Button variant="outline" size="sm" onClick={() => setCreating(true)}>
              <Plus size={13} /> {t("batchCreate")}
            </Button>
          </div>
          <div className="plugins-list-body">
            {(batches.data ?? []).map((batch) => {
              const done = (batch.items ?? []).filter((item) => !ACTIVE.has(item.status) && item.status !== "pending").length;
              return (
                <ContextMenu key={batch.id}>
                  <ContextMenuTrigger asChild>
                    <button
                      type="button"
                      className={selected?.id === batch.id ? "plugins-item active" : "plugins-item"}
                      onClick={() => setSelectedId(batch.id)}
                    >
                      <span className={ACTIVE.has(batch.status) ? "plugins-dot on" : "plugins-dot"} />
                      <span className="plugins-item-text">
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
        <div className="plugins-detail">
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
    <div className="plugins-detail-body">
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
          <div className="batch-progress-cell">
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
    <div className={`batch-item batch-${item.status}`}>
      <span className="batch-item-index timecode">#{item.index + 1}</span>
      <span className="batch-item-params" title={paramsSummary}>
        {paramsSummary}
      </span>
      <span className="batch-item-status">
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
        <span className="batch-item-error" title={item.error}>
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
      <div className="task-create-form batch-create-form">
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
            <div className="batch-rows">
              {rows.map((row, rowIndex) => (
                <div className="batch-row" key={rowIndex}>
                  <span className="timecode batch-row-index">#{rowIndex + 1}</span>
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
                    <span className="batch-row-noparams">{t("batchNoParams")}</span>
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
