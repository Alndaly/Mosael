import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, CheckCircle2, CircleAlert, Loader2, Play, Timer, Trash2 } from "lucide-react";

import {
  api,
  type Job,
  type Project,
  type RunScheduledTaskResponse,
  type ScheduledTask,
  type ScheduledTaskRun,
  type Workspace,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { SettingsBlock, SettingsGroup, SettingsRow } from "@/features/settings/ui";

/**
 * 定时任务页 = 主从布局(与插件页同一设计语言):左列任务列表,
 * 右侧选中任务的详情(概览行 + 运行记录)。
 */
export function SchedulerView({ workspace, project }: { workspace: Workspace; project: Project | null }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  const tasks = useQuery({
    queryKey: ["scheduled-tasks", workspace.id],
    queryFn: () => api<ScheduledTask[]>(`/api/scheduled-tasks?workspace_id=${workspace.id}`),
  });
  const createTask = useMutation({
    mutationFn: () =>
      api<ScheduledTask>("/api/scheduled-tasks", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspace.id,
          project_id: project?.id ?? null,
          name: t("hourlyRenderCheck"),
          kind: "render",
          trigger_type: "interval",
          schedule: { seconds: 3600 },
          payload: { project_id: project?.id ?? null },
        }),
      }),
    onSuccess: (task) => {
      setSelectedId(task.id);
      void qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspace.id] });
    },
  });

  const selected =
    (tasks.data ?? []).find((task) => task.id === selectedId) ?? (tasks.data ?? [])[0] ?? null;

  // 一个任务都没有:整页一个居中空状态,不摆空的主从骨架(否则
  // 列表和详情各出一个空提示,像坏掉了一样)。
  if (tasks.isSuccess && (tasks.data ?? []).length === 0) {
    return (
      <div className="feature-view">
        <EmptyState
          icon={<Timer size={22} />}
          title={t("noTasks")}
          body={t("noTasksGuide")}
          action={
            <Button disabled={createTask.isPending} onClick={() => createTask.mutate()}>
              <CalendarClock size={15} /> {t("createTask")}
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="feature-view">
      <div className="plugins-shell">
        <aside className="plugins-list panel">
          <div className="panel-head">
            <h2>{t("tasks")}</h2>
            <Button variant="outline" size="sm" disabled={createTask.isPending} onClick={() => createTask.mutate()}>
              <CalendarClock size={13} /> {t("createTask")}
            </Button>
          </div>
          <div className="plugins-list-body">
            {(tasks.data ?? []).map((task) => (
              <button
                key={task.id}
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
            ))}
          </div>
        </aside>
        <div className="plugins-detail">
          {selected ? (
            <TaskDetail key={selected.id} task={selected} workspaceId={workspace.id} />
          ) : (
            <EmptyState icon={<Timer size={22} />} title={t("noTasks")} body={t("noTasksGuide")} />
          )}
        </div>
      </div>
    </div>
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
            <div className="seg" role="tablist">
              <button
                type="button"
                className={task.enabled ? "seg-btn" : "seg-btn active"}
                onClick={() => toggleTask.mutate(false)}
              >
                {t("pluginOff")}
              </button>
              <button
                type="button"
                className={task.enabled ? "seg-btn active" : "seg-btn"}
                onClick={() => toggleTask.mutate(true)}
              >
                {t("pluginOn")}
              </button>
            </div>
          </div>
        }
      >
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
          {(runs.data ?? []).map((run) => (
            <RunRow key={run.id} run={run} job={jobs.data?.find((job) => job.id === run.job_id) ?? null} />
          ))}
          {runs.data?.length === 0 && <p className="feishu-empty">{t("noRunsYet")}</p>}
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
  const running = run.status === "queued" || run.status === "running";
  return (
    <div className={running ? "taskrow running" : `taskrow ${run.status}`}>
      <span className="taskrow-icon">
        {running ? (
          <Loader2 size={13} className="spin" />
        ) : run.status === "succeeded" ? (
          <CheckCircle2 size={13} className="inv-ok" />
        ) : (
          <CircleAlert size={13} className="inv-bad" />
        )}
      </span>
      <div className="taskrow-body">
        <div className="taskrow-title">
          <strong className="timecode">{(run.started_at ?? "").replace("T", " ").slice(0, 19) || run.status}</strong>
          <span className="taskrow-status">{run.status}</span>
        </div>
        <small className="taskrow-msg" title={run.error ?? job?.message ?? ""}>
          {run.error ?? job?.message ?? ""}
        </small>
      </div>
    </div>
  );
}
