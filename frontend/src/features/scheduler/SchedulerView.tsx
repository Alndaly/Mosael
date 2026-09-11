import { CollectionDetail, COLLECTION_DETAIL_PAGE, COLLECTION_DETAIL_HEADING, DETAIL_INDEX_ITEM, DETAIL_INDEX_SELECTED, DETAIL_INDEX_TEXT } from "@/components/layout/CollectionDetail";
import React from "react";
import { PageHeading } from "@/components/layout/StudioPage";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, GitBranch, CalendarClock, CheckCircle2, CircleAlert, Copy, Loader2, Play, Plus, Power, Timer, Trash2, Users2 } from "lucide-react";
import { toast } from "sonner";

import {
  API_BASE,
  createScheduledTask,
  deleteScheduledTask,
  listJobs,
  listScheduledTaskRuns,
  listScheduledTasks,
  listWorkflows,
  runScheduledTask,
  setResourceShared,
  updateScheduledTask,
  type Job,
  type Project,
  type ScheduledTask,
  type ScheduledTaskRun,
  type Workflow,
  type Workspace,
} from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { JobChildrenList, useJobChildren } from "@/components/layout/JobChildren";
import { relativeTime } from "@/lib/time";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Combobox } from "@/components/app/combobox";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SettingsRow } from "@/features/settings/ui";
import { usePersistentSelection } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";

/**
 * 定时任务页 = 主从布局(与插件页同一设计语言):左列任务列表,
 * 右侧选中任务的详情(概览行 + 运行记录)。
 */
export function SchedulerView({ workspace, project }: { workspace: Workspace; project: Project | null }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [creating, setCreating] = React.useState(false);
  const [menuDeleting, setMenuDeleting] = React.useState<ScheduledTask | null>(null);

  const tasks = useQuery({
    queryKey: ["scheduled-tasks", workspace.id],
    queryFn: () => listScheduledTasks(workspace.id),
  });
  const refreshTasks = () => void qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspace.id] });
  // 定时任务默认共享(团队基建),但主人可以把它收成自己的 —— 归属决定的是谁能改、事后谁负责。
  const menuShare = useMutation({
    mutationFn: ({ id, shared }: { id: string; shared: boolean }) =>
      setResourceShared("scheduled_task", id, workspace.id, shared),
    onSuccess: refreshTasks,
  });
  const menuRun = useMutation({
    mutationFn: runScheduledTask,
    onSuccess: refreshTasks,
  });
  const menuToggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      updateScheduledTask(id, { enabled }),
    onSuccess: refreshTasks,
  });
  const menuRemove = useMutation({
    mutationFn: deleteScheduledTask,
    onSuccess: () => {
      setMenuDeleting(null);
      refreshTasks();
    },
  });

  // 选中的那一个**活过导航** —— 切走再回来还停在他刚才看的那条(见 lib/usePersistentTab)。
  // 它被删掉时自动回落到列表第一条,那正是下面这行本来就在做的事。
  const [selectedId, setSelectedId] = usePersistentSelection(
    "scheduler",
    tasks.data?.map((task) => task.id),
  );
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
      <div className={COLLECTION_DETAIL_PAGE}>
        <PageHeading className={COLLECTION_DETAIL_HEADING} title={t("tasks")} description={t("studioSchedulerDesc")} />
        <div className="flex min-h-0 flex-1 overflow-y-auto">
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
        </div>
        {createDialog}
      </div>
    );
  }

  return (
    <div className={COLLECTION_DETAIL_PAGE}>
      <PageHeading className={COLLECTION_DETAIL_HEADING} title={t("tasks")} description={t("studioSchedulerDesc")} count={tasks.data?.length} actions={<Button onClick={() => setCreating(true)}><Plus />{t("createTask")}</Button>} />
      <CollectionDetail storageKey="scheduler" label={t("tasks")} selected={!!selected} index={<>
            {tasks.isLoading &&
              (tasks.data ?? []).length === 0 &&
              [0, 1, 2, 3].map((i) => (
                <div key={`sk${i}`} className="flex items-center gap-[9px] px-2 py-1.5" aria-hidden>
                  <div className="grid min-w-0 flex-1 gap-1.5">
                    <Skeleton className="h-3.5 w-3/4 rounded" />
                    <Skeleton className="h-2.5 w-1/3 rounded" />
                  </div>
                </div>
              ))}
            {(tasks.data ?? []).map((task) => (
              <ContextMenu key={task.id}>
                <ContextMenuTrigger asChild>
                  <button
                    type="button"
                    className={cn(DETAIL_INDEX_ITEM, selected?.id === task.id && DETAIL_INDEX_SELECTED)}
                    aria-current={selected?.id === task.id ? "true" : undefined}
                    onClick={() => setSelectedId(task.id)}
                  >
                    <span className={cn("h-[7px] w-[7px] shrink-0 rounded-full bg-border-strong", task.enabled && "bg-success")} />
                    <span className={DETAIL_INDEX_TEXT}>
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
                  {task.is_mine && (
                    <ContextMenuItem onSelect={() => menuShare.mutate({ id: task.id, shared: !task.shared })}>
                      <Users2 /> {task.shared ? t("taskUnshare") : t("taskShare")}
                    </ContextMenuItem>
                  )}
                  <ContextMenuSeparator />
                  <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => setMenuDeleting(task)}>
                    <Trash2 /> {t("delete")}
                  </ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
            ))}
      </>}>
          {selected ? (
            <TaskDetail key={selected.id} task={selected} workspaceId={workspace.id} />
          ) : (
            <EmptyState icon={<Timer size={22} />} title={t("pickDetailTitle")} body={t("pickDetailBody")} />
          )}
      </CollectionDetail>
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
      <div className="flex min-w-0 max-w-[420px] items-center gap-1">
        <code className="timecode max-w-[320px] truncate text-xs text-muted-foreground" title={url}>
          {url}
        </code>
        <Button
          size="icon"
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
  /**
   * 绑了一个 id、却在列表里找不到它 —— 说明那个工作流**已经被删了**,而任务还指着它:
   * 这个任务一旦触发就会失败。此前这种情况下按钮里显示的是**那串裸 UUID**,既看不出是哪个
   * 工作流(它已经没有名字了),也看不出这是个故障 —— 一个 32 位十六进制串是给人看的东西里
   * 最无用的那种。
   *
   * 「还没读到」和「读过了,不在」必须分开:前者是暂时的,后者才是结论。混成一个的话,
   * 列表还在路上时每个任务都会先诬告自己一遍「工作流已删除」。
   */
  const pending = workflows.isPending;
  const missing = Boolean(workflowId) && !pending && !workflow;
  const label = !workflowId
    ? t("taskNoWorkflow")
    : workflow
      ? workflow.name
      : pending
        ? t("taskWorkflowLoading")
        : t("taskWorkflowGone");
  return (
    <SettingsRow
      label={t("wfBoundWorkflow")}
      description={missing ? t("taskWorkflowGoneDesc") : workflow?.description || t("taskWorkflowDesc")}
    >
      {/* 按钮内容是工作流的**名字**,而用户的工作流常叫「新工作流」—— 光秃秃一个名字
          看起来像「新建工作流」动作按钮。图标 + 悬停说明把它钉回「这是当前绑定,点击去看」。 */}
      <Button
        variant="outline"
        className={cn("max-w-full", missing && "border-destructive/50 text-destructive")}
        title={t("taskOpenWorkflow")}
        onClick={() => (window.location.hash = "#/workflows")}
      >
        {missing ? <AlertTriangle size={13} /> : <GitBranch size={13} />}
        <span className="truncate">{label}</span>
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
      return createScheduledTask({
        workspace_id: workspace.id,
        project_id: project?.id ?? null,
        name: name.trim() || selectedWorkflow?.name || t("createTask"),
        kind: "workflow",
        trigger_type,
        schedule,
        payload: { workflow_id: workflowId, params: {} },
      });
    },
    onSuccess: onCreated,
  });

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title={t("createTask")}
      footer={
        <>
          <Button variant="outline" size="sm" onClick={onClose}>{t("cancel")}</Button>
          <Button size="sm" disabled={!workflowId} loading={create.isPending} onClick={() => create.mutate()}>
            <CalendarClock size={13} /> {t("createTask")}
          </Button>
        </>
      }
    >
      <div className="grid gap-2.5 [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
        <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-ui-xs [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-ui-sm [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
          <span>{t("taskNameLabel")}</span>
          <Input value={name} placeholder={selectedWorkflow?.name ?? ""} onChange={(event) => setName(event.target.value)} />
        </div>
        <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-ui-xs [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-ui-sm [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
          <span>{t("wfBoundWorkflow")}</span>
          <Combobox
            value={workflowId ?? ""}
            options={(workflows.data ?? []).map((workflow: Workflow) => ({ value: workflow.id, label: workflow.name }))}
            placeholder={t("wfPickWorkflow")}
            emptyText={t("cmdkEmpty")}
            className="w-full"
            onValueChange={setWorkflowId}
          />
          {(workflows.data ?? []).length === 0 && workflows.isSuccess && (
            <small>{t("noWorkflowHint")}</small>
          )}
          {selectedWorkflow?.description && <small>{selectedWorkflow.description}</small>}
        </div>
        <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-ui-xs [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-ui-sm [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
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
        </div>
        {trigger === "scheduled" && (
          <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-ui-xs [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-ui-sm [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
            <span>{t("taskSchedFreq")}</span>
            <div className="flex gap-1.5 [&>button]:min-w-0 [&>button]:flex-1 [&_input[type=time]]:w-[120px] [&_input[type=time]]:flex-none">
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
                // 原生 time 控件不吃继承字号、拨盘图标也不跟主题:字号/等宽数字压回
                // 表单刻度,color-scheme 随昼夜让时钟图标同色,图标半透明 hover 提亮。
                <Input
                  type="time"
                  className="tabular-nums [color-scheme:light] dark:[color-scheme:dark] [&::-webkit-calendar-picker-indicator]:cursor-pointer [&::-webkit-calendar-picker-indicator]:opacity-60 hover:[&::-webkit-calendar-picker-indicator]:opacity-100 [&::-webkit-datetime-edit]:text-ui-sm"
                  value={dailyTime}
                  onChange={(event) => setDailyTime(event.target.value || "09:00")}
                />
              )}
            </div>
          </div>
        )}
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
    queryFn: () => listScheduledTaskRuns(task.id),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((run) => run.status === "queued" || run.status === "running") ? 2000 : false,
    refetchOnWindowFocus: true,
  });
  const jobs = useQuery({
    queryKey: ["jobs", workspaceId, "all"],
    queryFn: () => listJobs(workspaceId),
  });

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspaceId] });
    void qc.invalidateQueries({ queryKey: ["task-runs", task.id] });
  };
  const toggleTask = useMutation({
    mutationFn: (enabled: boolean) => updateScheduledTask(task.id, { enabled }),
    onSuccess: refresh,
  });
  const runTask = useMutation({
    mutationFn: () => runScheduledTask(task.id),
    onSuccess: () => {
      refresh();
      void qc.invalidateQueries({ queryKey: ["jobs", workspaceId, "all"] });
    },
  });
  const { locale } = usePreferences();
  const deleteTask = useMutation({
    mutationFn: () => deleteScheduledTask(task.id),
    onSuccess: () => {
      setDeleting(false);
      void qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspaceId] });
    },
  });

  // 计划一栏说人话:手动/Webhook 任务的 schedule 本来就是空的,把 `{}` 原样端给用户
  // 只会让人以为坏了。真有结构而这里不认识的,才退回 JSON —— 那时原文就是信息。
  const scheduleLabel =
    task.trigger_type === "interval" && task.schedule?.seconds
      ? t("everySeconds").replace("{s}", String(task.schedule.seconds))
      : task.trigger_type === "manual"
        ? t("trigger_manual")
        : task.trigger_type === "webhook"
          ? t("trigger_webhook")
          : Object.keys(task.schedule ?? {}).length === 0
            ? t("schedNone")
            : JSON.stringify(task.schedule);

  // 后端时间是 UTC 无时区标记的 ISO 串;补 Z 再按本地时区、当前语言给人读。
  const localTime = (iso: string | null | undefined) => {
    if (!iso) return null;
    const normalized = /Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
    return new Date(normalized).toLocaleString(locale, {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    });
  };

  return (
    <div className="grid w-full min-w-0 content-start gap-6">
      {/* **页头,不是卡片。** 任务名是这一页的身份 —— 它此前和运行记录一样是个 SettingsGroup,
          两块等重,而真正天天看的是下面那份记录。 */}
      <header className="grid gap-5 border-b border-divider pb-5">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <h2 className="m-0 truncate text-xl font-semibold text-foreground">{task.name}</h2>
          <div className="flex shrink-0 items-center gap-1.5">
            <Button variant="outline" disabled={!task.enabled} loading={runTask.isPending} onClick={() => runTask.mutate()}>
              <Play size={13} /> {t("runNow")}
            </Button>
            <label className="inline-flex h-10 cursor-pointer select-none items-center gap-2 rounded-md border border-border px-3 text-ui-sm text-muted-foreground">
              <span>{task.enabled ? t("pluginOn") : t("pluginOff")}</span>
              <Switch checked={task.enabled} onCheckedChange={(checked) => toggleTask.mutate(checked)} />
            </label>
          </div>
        </div>
        {/* 计划 / 下次 / 上次是**三个短事实**,不是三件要操作的事 —— 它们此前各占一整行,
            每行还配一句说明,读三个时间戳要扫过六行字。摆成一排。 */}
        <dl className="m-0 grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-4 text-ui-xs [&_dd]:m-0 [&_dd]:text-foreground [&_dt]:text-muted-foreground">
          <div className="grid min-w-0 content-start gap-1.5 [&_dd]:text-ui-sm [&_dd]:break-words">
            <dt>{t("taskSchedule")}</dt>
            <dd className="tabular-nums">{scheduleLabel}</dd>
          </div>
          <div className="grid min-w-0 content-start gap-1.5 [&_dd]:text-ui-sm [&_dd]:break-words">
            <dt>{t("taskNextRun")}</dt>
            <dd className="tabular-nums">{localTime(task.next_run_at) ?? t("manualNoSchedule")}</dd>
          </div>
          <div className="grid min-w-0 content-start gap-1.5 [&_dd]:text-ui-sm [&_dd]:break-words">
            <dt>{t("taskLastRun")}</dt>
            <dd className="tabular-nums">{localTime(task.last_run_at) ?? "—"}</dd>
          </div>
        </dl>
      </header>

      {/* 绑定与 webhook 是**要动手的**,但不需要再套卡片。详情页本身已经有完整边界,
          这里用行间分隔就够了;额外的圆角框只会形成框中框。 */}
      {(task.kind === "workflow" || task.trigger_type === "webhook") && (
        <div className="grid divide-y divide-divider">
          {task.kind === "workflow" && <BoundWorkflowRow task={task} workspaceId={workspaceId} />}
          {task.trigger_type === "webhook" && <WebhookUrlRow task={task} />}
        </div>
      )}

      {/* **运行记录是主体**,所以它占最大一块,而且不再被上面那堆只读行挤到屏幕外。 */}
      <section className="grid gap-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="m-0 text-ui-md font-semibold text-foreground">{t("taskRuns")}</h3>
          <span className="text-ui-xs text-muted-foreground">{t("taskRunsDesc")}</span>
        </div>
        {/* 行自己不带边框(靠 [&+&]:border-t 分隔),所以左右内边距要由容器给 ——
            少了它,每一行都贴着边框,而图标离边只有 1px。 */}
        <div className="overflow-hidden rounded-md border border-border px-4">
          {(runs.data ?? []).map((run) => (
            <RunRow key={run.id} run={run} job={jobs.data?.find((job) => job.id === run.job_id) ?? null} />
          ))}
          {runs.data?.length === 0 && (
            <EmptyState size="compact" icon={<Timer />} title={t("noRunsYet")} />
          )}
        </div>
      </section>

      {/* 删除排在最后、样子最轻 —— 危险操作不该和日常操作抢同一个视觉分量。 */}
      <div className="flex items-center justify-between gap-3 border-t border-divider pt-3">
        <p className="m-0 text-ui-xs leading-[1.55] text-muted-foreground">{t("deleteTaskDesc")}</p>
        <Button
          size="sm"
          variant="ghost"
          className="shrink-0 text-muted-foreground hover:text-destructive"
          onClick={() => setDeleting(true)}
        >
          <Trash2 size={13} /> {t("delete")}
        </Button>
      </div>

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
  //: 这一次运行派生的子任务。**只在跑着的时候拉** —— 历史里几十条各拉一次是白花请求,
  //: 而"它到底在动没动"这个问题只有当下那一条会问。
  //:
  //: 定时任务跑工作流时复用同一个 job(见 workers/scheduler),所以工作流里那些出片、配音
  //: 都挂在这条运行下面。不摆出来的话,一次十几分钟的成片任务在这里就是一个不动的转圈。
  const children = useJobChildren(running ? run.job_id ?? null : null, running);
  const rows = children.data ?? [];

  return (
    <div className="grid gap-1 py-3 [&+&]:border-t [&+&]:border-divider">
      <div className="flex items-center gap-2">
      <span
        className={cn(
          "grid h-[22px] w-[22px] shrink-0 place-items-center rounded-full border border-border text-muted-foreground",
          running && "border-[color-mix(in_srgb,var(--primary)_35%,var(--border))] bg-[color-mix(in_srgb,var(--primary)_8%,transparent)] text-primary",
          !running && run.status === "succeeded" && "border-[color-mix(in_srgb,var(--success)_35%,var(--border))] bg-[color-mix(in_srgb,var(--success)_8%,transparent)] text-success",
          !running && run.status === "failed" && "border-[color-mix(in_srgb,var(--destructive)_35%,var(--border))] bg-[color-mix(in_srgb,var(--destructive)_8%,transparent)] text-destructive",
        )}
      >
        {running ? (
          <Loader2 size={12} className="animate-mosael-spin" />
        ) : run.status === "succeeded" ? (
          <CheckCircle2 size={12} />
        ) : (
          <CircleAlert size={12} />
        )}
      </span>
      <div className="grid min-w-0 flex-1 gap-px">
        <div className="flex min-w-0 items-baseline gap-1.5 [&_strong]:whitespace-nowrap [&_strong]:text-ui-sm">
          <strong>{run.started_at ? relativeTime(run.started_at, locale) : t(`runStatus_${run.status}` as never)}</strong>
          {run.started_at && (
            <span className="timecode text-ui-xs text-muted-foreground">{run.started_at.replace("T", " ").slice(5, 19)}</span>
          )}
        </div>
        {message && (
          <small className="truncate text-ui-xs text-muted-foreground" title={message}>
            {message}
          </small>
        )}
      </div>
      {durationText && <span className="timecode shrink-0 text-ui-xs text-muted-foreground">{durationText}</span>}
      <em
        className={cn(
          "shrink-0 rounded-full bg-secondary px-2 text-ui-2xs not-italic leading-[18px] text-muted-foreground",
          running && "bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-primary",
          !running && run.status === "succeeded" && "bg-[color-mix(in_srgb,var(--success)_12%,transparent)] text-success",
          !running && run.status === "failed" && "bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] text-destructive",
          !running && run.status === "queued" && "bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-primary",
        )}
      >
        {t(`runStatus_${running ? "running" : run.status}` as never)}
      </em>
      </div>
      {rows.length > 0 && (
        <div className="pl-[30px]">
          <JobChildrenList>{rows}</JobChildrenList>
        </div>
      )}
    </div>
  );
}
