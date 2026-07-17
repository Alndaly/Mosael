import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, CheckCircle2, CircleAlert, Copy, Loader2, Play, Power, Timer, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  API_BASE,
  api,
  listWorkflows,
  type Job,
  type Project,
  type RunScheduledTaskResponse,
  type ScheduledTask,
  type ScheduledTaskRun,
  type Workflow,
  type Workspace,
} from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { relativeTime } from "@/lib/time";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { ConfirmDialog, ModalShell } from "@/components/ui/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SettingsBlock, SettingsGroup, SettingsRow } from "@/features/settings/ui";

/**
 * 定时任务页 = 主从布局(与插件页同一设计语言):左列任务列表,
 * 右侧选中任务的详情(概览行 + 运行记录)。
 */
export function SchedulerView({ workspace, project }: { workspace: Workspace; project: Project | null }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState(false);
  const [menuDeleting, setMenuDeleting] = React.useState<ScheduledTask | null>(null);

  const tasks = useQuery({
    queryKey: ["scheduled-tasks", workspace.id],
    queryFn: () => api<ScheduledTask[]>(`/api/scheduled-tasks?workspace_id=${workspace.id}`),
  });
  const refreshTasks = () => void qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspace.id] });
  const menuRun = useMutation({
    mutationFn: (id: string) => api<RunScheduledTaskResponse>(`/api/scheduled-tasks/${id}/run`, { method: "POST" }),
    onSuccess: refreshTasks,
  });
  const menuToggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api<ScheduledTask>(`/api/scheduled-tasks/${id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
    onSuccess: refreshTasks,
  });
  const menuRemove = useMutation({
    mutationFn: (id: string) => api(`/api/scheduled-tasks/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setMenuDeleting(null);
      refreshTasks();
    },
  });

  const selected =
    (tasks.data ?? []).find((task) => task.id === selectedId) ?? (tasks.data ?? [])[0] ?? null;

  // 一个任务都没有:整页一个居中空状态,不摆空的主从骨架(否则
  // 列表和详情各出一个空提示,像坏掉了一样)。
  const createDialog = (
    <CreateTaskDialog
      open={creating}
      workspace={workspace}
      project={project}
      onClose={() => setCreating(false)}
      onCreated={(task) => {
        setCreating(false);
        setSelectedId(task.id);
        void qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspace.id] });
      }}
    />
  );

  if (tasks.isSuccess && (tasks.data ?? []).length === 0) {
    return (
      <div className="feature-view">
        <EmptyState
          icon={<Timer size={22} />}
          title={t("noTasks")}
          body={t("noTasksGuide")}
          action={
            <Button onClick={() => setCreating(true)}>
              <CalendarClock size={15} /> {t("createTask")}
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
            <h2>{t("tasks")}</h2>
            <Button variant="outline" size="sm" onClick={() => setCreating(true)}>
              <CalendarClock size={13} /> {t("createTask")}
            </Button>
          </div>
          <div className="plugins-list-body">
            {(tasks.data ?? []).map((task) => (
              <ContextMenu key={task.id}>
                <ContextMenuTrigger asChild>
                  <button
                    type="button"
                    className={selected?.id === task.id ? "plugins-item active" : "plugins-item"}
                    onClick={() => setSelectedId(task.id)}
                  >
                    <span className={task.enabled ? "plugins-dot on" : "plugins-dot"} />
                    <span className="plugins-item-text">
                      <strong>{task.name}</strong>
                      <small>
                        {t(`taskKind_${task.kind}` as never)} · {t(`trigger_${task.trigger_type}` as never)}
                      </small>
                    </span>
                  </button>
                </ContextMenuTrigger>
                <ContextMenuContent>
                  <ContextMenuItem disabled={!task.enabled} onSelect={() => menuRun.mutate(task.id)}>
                    <Play /> {t("runNow")}
                  </ContextMenuItem>
                  <ContextMenuItem onSelect={() => menuToggle.mutate({ id: task.id, enabled: !task.enabled })}>
                    <Power /> {task.enabled ? t("pluginOff") : t("pluginOn")}
                  </ContextMenuItem>
                  <ContextMenuSeparator />
                  <ContextMenuItem destructive onSelect={() => setMenuDeleting(task)}>
                    <Trash2 /> {t("delete")}
                  </ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
            ))}
          </div>
        </aside>
        <div className="plugins-detail">
          {selected ? (
            <TaskDetail key={selected.id} task={selected} workspaceId={workspace.id} />
          ) : (
            <EmptyState icon={<Timer size={22} />} title={t("pickDetailTitle")} body={t("pickDetailBody")} />
          )}
        </div>
      </div>
      {createDialog}
      <ConfirmDialog
        open={menuDeleting !== null}
        title={t("deleteConfirmTitle")}
        body={t("deleteTaskDesc")}
        onCancel={() => setMenuDeleting(null)}
        onConfirm={() => menuDeleting && menuRemove.mutate(menuDeleting.id)}
      />
    </div>
  );
}

/** Webhook 任务的触发地址:POST 该 URL 即触发一次运行,密钥即凭证。 */
function WebhookUrlRow({ task }: { task: ScheduledTask }) {
  const t = useI18n();
  const secret = String((task.payload as { webhook_secret?: string })?.webhook_secret ?? "");
  const url = `${API_BASE}/api/hooks/scheduled-tasks/${task.id}?secret=${secret}`;
  return (
    <SettingsRow label={t("webhookUrlLabel")} description={t("webhookUrlDesc")}>
      <div className="webhook-url-cell">
        <code className="timecode sg-value webhook-url" title={url}>
          {url}
        </code>
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label={t("copy")}
          onClick={() => {
            void navigator.clipboard.writeText(url);
            toast.success(t("webhookCopied"));
          }}
        >
          <Copy size={13} />
        </Button>
      </div>
    </SettingsRow>
  );
}

/** 任务详情里的"这个任务做什么":显示绑定的工作流,点击跳到工作流页。 */
function BoundWorkflowRow({ task, workspaceId }: { task: ScheduledTask; workspaceId: string }) {
  const t = useI18n();
  const workflows = useQuery({
    queryKey: ["workflows", workspaceId],
    queryFn: () => listWorkflows(workspaceId),
  });
  const workflowId = String((task.payload as { workflow_id?: string })?.workflow_id ?? "");
  const workflow = (workflows.data ?? []).find((item) => item.id === workflowId) ?? null;
  return (
    <SettingsRow
      label={t("wfBoundWorkflow")}
      description={workflow?.description || t("taskWorkflowDesc")}
    >
      <Button size="sm" variant="outline" onClick={() => (window.location.hash = "#/workflows")}>
        {workflow?.name ?? workflowId ?? "—"}
      </Button>
    </SettingsRow>
  );
}

/** 新建任务 = 名称 + 绑定工作流 + 触发方式:任务的"做什么"由工作流承载。 */
function CreateTaskDialog({
  open,
  workspace,
  project,
  onClose,
  onCreated,
}: {
  open: boolean;
  workspace: Workspace;
  project: Project | null;
  onClose: () => void;
  onCreated: (task: ScheduledTask) => void;
}) {
  const t = useI18n();
  const [name, setName] = React.useState("");
  const [workflowId, setWorkflowId] = React.useState<string | null>(null);
  const [trigger, setTrigger] = React.useState<"manual" | "scheduled" | "webhook">("manual");
  const [schedKind, setSchedKind] = React.useState<"hourly" | "daily">("hourly");
  const [dailyTime, setDailyTime] = React.useState("09:00");

  const workflows = useQuery({
    queryKey: ["workflows", workspace.id],
    queryFn: () => listWorkflows(workspace.id),
    enabled: open,
  });
  const selectedWorkflow = (workflows.data ?? []).find((workflow) => workflow.id === workflowId) ?? null;

  const create = useMutation({
    mutationFn: () => {
      const trigger_type =
        trigger === "scheduled" ? (schedKind === "hourly" ? "interval" : "daily") : trigger;
      const schedule =
        trigger !== "scheduled" ? {} : schedKind === "hourly" ? { seconds: 3600 } : { time: dailyTime };
      return api<ScheduledTask>("/api/scheduled-tasks", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspace.id,
          project_id: project?.id ?? null,
          name: name.trim() || selectedWorkflow?.name || t("createTask"),
          kind: "workflow",
          trigger_type,
          schedule,
          payload: { workflow_id: workflowId, params: {} },
        }),
      });
    },
    onSuccess: onCreated,
  });

  return (
    <ModalShell open={open} onOpenChange={(next) => !next && onClose()} title={t("createTask")}>
      <div className="task-create-form">
        <label className="wf-field">
          <span>{t("taskNameLabel")}</span>
          <Input value={name} placeholder={selectedWorkflow?.name ?? ""} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="wf-field">
          <span>{t("wfBoundWorkflow")}</span>
          <Select value={workflowId ?? ""} onValueChange={setWorkflowId}>
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
          {(workflows.data ?? []).length === 0 && workflows.isSuccess && (
            <small>{t("noWorkflowHint")}</small>
          )}
          {selectedWorkflow?.description && <small>{selectedWorkflow.description}</small>}
        </label>
        <label className="wf-field">
          <span>{t("taskTriggerLabel")}</span>
          <Select value={trigger} onValueChange={(value) => setTrigger(value as typeof trigger)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="manual">{t("trigger_manual")}</SelectItem>
              <SelectItem value="scheduled">{t("triggerScheduled")}</SelectItem>
              <SelectItem value="webhook">Webhook</SelectItem>
            </SelectContent>
          </Select>
          {trigger === "webhook" && <small>{t("webhookCreateHint")}</small>}
        </label>
        {trigger === "scheduled" && (
          <div className="task-sched-config">
            <Select value={schedKind} onValueChange={(value) => setSchedKind(value as typeof schedKind)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="hourly">{t("triggerHourly")}</SelectItem>
                <SelectItem value="daily">{t("triggerDailyAt")}</SelectItem>
              </SelectContent>
            </Select>
            {schedKind === "daily" && (
              <Input
                type="time"
                value={dailyTime}
                onChange={(event) => setDailyTime(event.target.value || "09:00")}
              />
            )}
          </div>
        )}
        <div className="task-create-actions">
          <Button variant="outline" size="sm" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button size="sm" disabled={!workflowId || create.isPending} onClick={() => create.mutate()}>
            <CalendarClock size={13} /> {t("createTask")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

function TaskDetail({ task, workspaceId }: { task: ScheduledTask; workspaceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [deleting, setDeleting] = React.useState(false);

  const runs = useQuery({
    queryKey: ["task-runs", task.id],
    queryFn: () => api<ScheduledTaskRun[]>(`/api/scheduled-tasks/${task.id}/runs`),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((run) => run.status === "queued" || run.status === "running") ? 2000 : false,
    refetchIntervalInBackground: true,
  });
  const jobs = useQuery({
    queryKey: ["jobs", workspaceId, "all"],
    queryFn: () => api<Job[]>(`/api/jobs?workspace_id=${workspaceId}`),
  });

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspaceId] });
    void qc.invalidateQueries({ queryKey: ["task-runs", task.id] });
  };
  const toggleTask = useMutation({
    mutationFn: (enabled: boolean) =>
      api<ScheduledTask>(`/api/scheduled-tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: refresh,
  });
  const runTask = useMutation({
    mutationFn: () => api<RunScheduledTaskResponse>(`/api/scheduled-tasks/${task.id}/run`, { method: "POST" }),
    onSuccess: () => {
      refresh();
      void qc.invalidateQueries({ queryKey: ["jobs", workspaceId, "all"] });
    },
  });
  const deleteTask = useMutation({
    mutationFn: () => api(`/api/scheduled-tasks/${task.id}`, { method: "DELETE" }),
    onSuccess: () => {
      setDeleting(false);
      void qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspaceId] });
    },
  });

  const scheduleLabel =
    task.trigger_type === "interval" && task.schedule?.seconds
      ? t("everySeconds").replace("{s}", String(task.schedule.seconds))
      : JSON.stringify(task.schedule ?? {});

  return (
    <div className="plugins-detail-body">
      <SettingsGroup
        title={task.name}
        description={`${t(`taskKind_${task.kind}` as never)} · ${t(`trigger_${task.trigger_type}` as never)}`}
        actions={
          <div className="sched-actions">
            <Button size="sm" variant="outline" disabled={!task.enabled || runTask.isPending} onClick={() => runTask.mutate()}>
              <Play size={13} /> {t("runNow")}
            </Button>
            <label className="switch-field">
              <span>{task.enabled ? t("pluginOn") : t("pluginOff")}</span>
              <Switch checked={task.enabled} onCheckedChange={(checked) => toggleTask.mutate(checked)} />
            </label>
          </div>
        }
      >
        {task.kind === "workflow" && <BoundWorkflowRow task={task} workspaceId={workspaceId} />}
        {task.trigger_type === "webhook" && <WebhookUrlRow task={task} />}
        <SettingsRow label={t("taskSchedule")} description={t("taskScheduleDesc")}>
          <code className="timecode sg-value">{scheduleLabel}</code>
        </SettingsRow>
        <SettingsRow label={t("taskNextRun")} description={t("taskNextRunDesc")}>
          <code className="timecode sg-value">{task.next_run_at ?? t("manual")}</code>
        </SettingsRow>
        <SettingsRow label={t("taskLastRun")}>
          <code className="timecode sg-value">{task.last_run_at ?? "—"}</code>
        </SettingsRow>
        <SettingsRow label={t("deleteTask")} description={t("deleteTaskDesc")}>
          <Button size="sm" variant="outline" className="sched-delete" onClick={() => setDeleting(true)}>
            <Trash2 size={13} /> {t("delete")}
          </Button>
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title={t("taskRuns")} description={t("taskRunsDesc")}>
        <SettingsBlock>
          <div className="run-list">
            {(runs.data ?? []).map((run) => (
              <RunRow key={run.id} run={run} job={jobs.data?.find((job) => job.id === run.job_id) ?? null} />
            ))}
            {runs.data?.length === 0 && <p className="feishu-empty">{t("noRunsYet")}</p>}
          </div>
        </SettingsBlock>
      </SettingsGroup>

      <ConfirmDialog
        open={deleting}
        title={t("deleteConfirmTitle")}
        body={t("deleteTaskBody")}
        onCancel={() => setDeleting(false)}
        onConfirm={() => deleteTask.mutate()}
      />
    </div>
  );
}

function RunRow({ run, job }: { run: ScheduledTaskRun; job: Job | null }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const running = run.status === "queued" || run.status === "running";
  // 耗时:两端都有才算;运行中显示已流逝。
  const durationText = (() => {
    if (!run.started_at) return null;
    const start = new Date(/Z|[+-]\d\d:?\d\d$/.test(run.started_at) ? run.started_at : `${run.started_at}Z`).getTime();
    const end = run.finished_at
      ? new Date(/Z|[+-]\d\d:?\d\d$/.test(run.finished_at) ? run.finished_at : `${run.finished_at}Z`).getTime()
      : Date.now();
    const seconds = Math.max(0, (end - start) / 1000);
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  })();
  const message = run.error ?? (running ? job?.message : null);

  return (
    <div className="run-row">
      <span className={`run-dot ${running ? "running" : run.status}`}>
        {running ? (
          <Loader2 size={12} className="spin" />
        ) : run.status === "succeeded" ? (
          <CheckCircle2 size={12} />
        ) : (
          <CircleAlert size={12} />
        )}
      </span>
      <div className="run-body">
        <div className="run-line">
          <strong>{run.started_at ? relativeTime(run.started_at, locale) : t(`runStatus_${run.status}` as never)}</strong>
          {run.started_at && (
            <span className="run-abs timecode">{run.started_at.replace("T", " ").slice(5, 19)}</span>
          )}
        </div>
        {message && (
          <small className="run-msg" title={message}>
            {message}
          </small>
        )}
      </div>
      {durationText && <span className="run-duration timecode">{durationText}</span>}
      <em className={`run-status s-${running ? "running" : run.status}`}>
        {t(`runStatus_${running ? "running" : run.status}` as never)}
      </em>
    </div>
  );
}
