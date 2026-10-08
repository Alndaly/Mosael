import { CollectionDetail, COLLECTION_DETAIL_PAGE, COLLECTION_DETAIL_HEADING, DETAIL_INDEX_ITEM, DETAIL_INDEX_SELECTED, DETAIL_INDEX_TEXT } from "@/components/layout/CollectionDetail";
import React from "react";
import { PageHeading } from "@/components/layout/StudioPage";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CalendarClock, CheckCircle2, ChevronRight, CircleAlert, Copy, Loader2, Play, Plus, Power, RotateCcw, Timer, Trash2, Users2 } from "lucide-react";
import { toast } from "sonner";

import {
  API_BASE,
  createScheduledTask,
  deleteScheduledTask,
  attestRequestOf,
  listScheduledTaskRuns,
  resetWebhookSecret,
  listScheduledTasks,
  listWorkflows,
  runScheduledTask,
  setResourceShared,
  topLevelJobsQuery,
  updateScheduledTask,
  type JobSummary,
  type Project,
  type ScheduledTask,
  type ScheduledTaskRun,
  type Workflow,
  type Workspace,
} from "@/api/client";
import { useJobKinds } from "@/components/jobs/jobKinds";
import { runStatusText } from "@/components/jobs/runStatus";
import { AttestRevisionButton } from "@/features/workflows/AttestRevisionButton";
import { useI18n, usePreferences } from "@/app/preferences";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { JobChildrenList, useJobChildren } from "@/components/jobs/JobChildren";
import { elapsedSecondsBetween, formatElapsedSeconds, parseServerTime, relativeTime } from "@/lib/time";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { IconButton } from "@/components/ui/icon-button";
import { MenuItemBody } from "@/components/ui/menu";
import { Truncate } from "@/components/ui/truncate";
import { Input } from "@/components/ui/input";
import { TimePicker } from "@/components/ui/time-picker";
import { Combobox } from "@/components/app/combobox";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { EmptyState, PageLoadError } from "@/components/layout/EmptyState";
import { atLeast } from "@/components/layout/workspaceMenu";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { BoundWorkflowRow as BoundWorkflowRowView, isBoundWorkflowGone } from "./boundWorkflowRow";
import { hasActiveRun, TaskRunControls } from "./taskRunControls";
import { localTimeZone, nextRunText, scheduleText, scheduleUsesClock } from "./scheduleText";
import { TaskParamsForm } from "./TaskParamsForm";
import { formValuesFrom, missingRequired, runParamsFrom, startParamsOf } from "./taskParams";
import { errorText } from "@/api/errorMessage";
import { Hint } from "@/components/ui/tooltip";
import { SettingsRow } from "@/components/settings/settings-layout";
import { usePersistentSelection } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";

/** 一个任务的运行记录。详情页和右键菜单读同一份(同一个键、同一种轮询)。 */
function taskRunsQuery(taskId: string) {
  return {
    queryKey: ["task-runs", taskId],
    queryFn: () => listScheduledTaskRuns(taskId),
    // **空闲时也要问。** 此前只在「已经知道有一条在跑」时才轮询,而外部触发(webhook)、到点的
    // 排程、别的同事点的「立即运行」都不经过这个页面 —— 那一条前端根本不知道,于是永远等不到,
    // 非得刷新页面。有在跑的 2 秒一问,空闲 5 秒一问;页面在后台时 react-query 自己会停。
    refetchInterval: (query: { state: { data?: ScheduledTaskRun[] } }) => (hasActiveRun(query.state.data) ? 2000 : 5000),
    refetchOnWindowFocus: true,
  };
}

/**
 * 右键菜单里的「立即运行」。菜单打开才挂载,挂载时问一次这个任务有没有在跑 —— 列表上别的任务的运行
 * 记录平时没人取,不问的话菜单只能照常给一个点了就被后端拒绝的项。
 */
function TaskMenuRunItem({ task, blocked, onRun }: { task: ScheduledTask; blocked: boolean; onRun: () => void }) {
  const t = useI18n();
  const runs = useQuery(taskRunsQuery(task.id));
  const active = hasActiveRun(runs.data);
  return (
    <ContextMenuItem disabled={!task.enabled || blocked || runs.isPending || active} onSelect={onRun}>
      <MenuItemBody icon={<Play />} label={active ? t("runStatus_running") : t("runNow")} />
    </ContextMenuItem>
  );
}

function useWorkflows(workspaceId: string) {
  return useQuery({ queryKey: ["workflows", workspaceId], queryFn: () => listWorkflows(workspaceId) });
}

function boundWorkflowId(task: ScheduledTask): string {
  return String((task.payload as { workflow_id?: string })?.workflow_id ?? "");
}

/** 这个任务跑不起来:它绑的工作流已经删了(后端同一条规则见 scheduler.ensure_runnable)。 */
function useIsBlocked(workspaceId: string) {
  const workflows = useWorkflows(workspaceId);
  return (task: ScheduledTask) =>
    task.kind === "workflow" && isBoundWorkflowGone(boundWorkflowId(task), workflows.data ?? [], workflows.isPending);
}

/**
 * 定时任务页 = 主从布局(与插件页同一设计语言):左列任务列表,
 * 右侧选中任务的详情(概览行 + 运行记录)。
 */
export function SchedulerView({ workspace, project }: { workspace: Workspace; project: Project | null }) {
  const t = useI18n();
  const { kindOf } = useJobKinds();
  const qc = useQueryClient();
  const [creating, setCreating] = React.useState(false);
  const [menuDeleting, setMenuDeleting] = React.useState<ScheduledTask | null>(null);
  //: 触发密钥的原文只在生成它的那一次响应里(建 webhook 任务、重置密钥):记在这一页的内存里给主人看一眼,
  //: 离开这一页就没了 —— 库里只有哈希(体检 UM-02)。
  const [revealedSecrets, setRevealedSecrets] = React.useState<Record<string, string>>({});
  const reveal = React.useCallback((task: ScheduledTask) => {
    const secret = task.webhook_secret;
    if (secret) setRevealedSecrets((now) => ({ ...now, [task.id]: secret }));
  }, []);

  const tasks = useQuery({
    queryKey: ["scheduled-tasks", workspace.id],
    queryFn: () => listScheduledTasks(workspace.id),
  });
  const isBlocked = useIsBlocked(workspace.id);
  const refreshTasks = () => void qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspace.id] });
  // 定时任务默认共享(团队基建),但主人可以把它收成自己的 —— 归属决定的是谁能改、事后谁负责。
  const menuShare = useMutation({
    mutationFn: ({ id, shared }: { id: string; shared: boolean }) =>
      setResourceShared("scheduled_task", id, workspace.id, shared),
    onSuccess: refreshTasks,
  });
  const menuRun = useMutation({
    mutationFn: runScheduledTask,
    onSuccess: (_result, taskId) => {
      refreshTasks();
      void qc.invalidateQueries({ queryKey: ["task-runs", taskId] });
    },
    //: 菜单打开之后才冒出来的那一次(到点的排程、webhook)只有后端知道:它回 409「还没跑完」,
    //: 由全局的失败提示说出来(app/mutationErrors)。
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
        reveal(task);
        setSelectedId(task.id);
        void qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspace.id] });
      }}
    />
  );

  //: 只读成员建不了定时任务(后端要 `schedule`,即编辑及以上):按钮灰掉、悬停说为什么,而不是点了才收到一句 403(体检 UM-20)。
  const readOnly = !atLeast(workspace.role, "editor");
  const createButton = (content: React.ReactNode) => (
    <Hint disabledReason={readOnly ? t("roleReadOnlyHint") : undefined}>
      <Button data-create-task="" disabled={readOnly} onClick={() => setCreating(true)}>
        {content}
      </Button>
    </Hint>
  );

  //: 标题用「定时任务」:导航和面包屑都这么叫,而「任务」和顶栏的「任务中心」撞名(体检 UM-25)。
  if (tasks.isSuccess && (tasks.data ?? []).length === 0) {
    return (
      <div className={COLLECTION_DETAIL_PAGE}>
        <PageHeading className={COLLECTION_DETAIL_HEADING} title={t("schedulerTitle")} description={t("studioSchedulerDesc")} />
        <div className="flex min-h-0 flex-1 overflow-y-auto">
        <EmptyState
          icon={<Timer size={22} />}
          title={t("noTasks")}
          body={t("noTasksGuide")}
          action={createButton(<><CalendarClock size={15} /> {t("createTask")}</>)}
        />
        </div>
        {createDialog}
      </div>
    );
  }

  return (
    <div className={COLLECTION_DETAIL_PAGE}>
      <PageHeading className={COLLECTION_DETAIL_HEADING} title={t("schedulerTitle")} description={t("studioSchedulerDesc")} count={tasks.data?.length} actions={createButton(<><Plus />{t("createTask")}</>)} />
      <CollectionDetail storageKey="scheduler" label={t("schedulerTitle")} selected={!!selected} index={<>
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
            {tasks.isError && (tasks.data ?? []).length === 0 && (
              <PageLoadError size="compact" icon={<Timer size={15} />} error={tasks.error} onRetry={() => void tasks.refetch()} />
            )}
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
                      <Truncate as="strong">{task.name}</Truncate>
                      <small>
                        {kindOf(task.kind).label} · {t(`trigger_${task.trigger_type}` as never)}
                      </small>
                    </span>
                  </button>
                </ContextMenuTrigger>
                <ContextMenuContent>
                  {/* 管一个任务只有它的主人(后端 scheduler.manageable_task):别人的任务菜单里这几项灰掉。 */}
                  <TaskMenuRunItem task={task} blocked={isBlocked(task) || !task.is_mine} onRun={() => menuRun.mutate(task.id)} />
                  <ContextMenuItem
                    disabled={!task.is_mine || (!task.enabled && isBlocked(task))}
                    onSelect={() => menuToggle.mutate({ id: task.id, enabled: !task.enabled })}
                  >
                    <MenuItemBody icon={<Power />} label={task.enabled ? t("pluginOff") : t("pluginOn")} />
                  </ContextMenuItem>
                  {task.is_mine && (
                    <ContextMenuItem onSelect={() => menuShare.mutate({ id: task.id, shared: !task.shared })}>
                      <MenuItemBody icon={<Users2 />} label={task.shared ? t("taskUnshare") : t("taskShare")} />
                    </ContextMenuItem>
                  )}
                  <ContextMenuSeparator />
                  <ContextMenuItem disabled={!task.is_mine} className="text-destructive focus:text-destructive" onSelect={() => setMenuDeleting(task)}>
                    <MenuItemBody icon={<Trash2 />} label={t("delete")} />
                  </ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
            ))}
      </>}>
          {selected ? (
            <TaskDetail
              key={selected.id}
              task={selected}
              workspaceId={workspace.id}
              revealedSecret={revealedSecrets[selected.id]}
              onSecretIssued={reveal}
            />
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
        pending={menuRemove.isPending}
        onConfirm={() => menuDeleting && menuRemove.mutate(menuDeleting.id)}
      />
    </div>
  );
}

/**
 * Webhook 任务的触发地址:POST 该 URL 即触发一次运行,密钥即凭证。
 *
 * 同一把密钥还管着「查这次运行到哪了」和「取消它」(后端 api/routes/hooks)—— 此前外部系统
 * 触发完就只能干等。三条调用写在折叠的说明里,各自能复制。密钥泄漏了就重置:旧地址连同
 * 查进度、取消一起失效。
 *
 * **密钥只在生成它的那一次看得到**(建任务、重置之后,`revealed`):库里只存哈希。此前它明文躺在任务里,
 * 列表接口发给工作区里每个人,只读成员拿着它不用登录就能触发(体检 UM-02)。之后要新地址就重置。
 * 只存哈希之前就有的那一把(`webhook_secret_set_at` 为空)曾经对所有人可见,这里提醒主人重置一次。
 */
function WebhookUrlRow({
  task,
  workspaceId,
  revealed,
  onSecretIssued,
}: {
  task: ScheduledTask;
  workspaceId: string;
  revealed?: string;
  onSecretIssued: (task: ScheduledTask) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [confirming, setConfirming] = React.useState(false);
  const [showApi, setShowApi] = React.useState(false);
  const base = `${API_BASE}/api/hooks/scheduled-tasks/${task.id}`;
  const secret = revealed ?? "<secret>";
  const url = `${base}?secret=${secret}`;
  const ownerOnly = task.is_mine ? undefined : t("taskOwnerOnly");
  const reset = useMutation({
    mutationFn: () => resetWebhookSecret(task.id),
    onSuccess: (next) => {
      setConfirming(false);
      onSecretIssued(next);
      toast.success(t("webhookResetDone"));
      void qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspaceId] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const calls: [string, string][] = [
    [t("webhookApiTrigger"), `curl -X POST '${url}'`],
    [t("webhookApiStatus"), `curl '${base}/runs/<run_id>?secret=${secret}'`],
    [t("webhookApiCancel"), `curl -X POST '${base}/runs/<run_id>/cancel?secret=${secret}'`],
  ];
  const copy = (text: string, done: string) => {
    void navigator.clipboard.writeText(text);
    toast.success(done);
  };
  return (
    <div className="grid">
      <SettingsRow label={t("webhookUrlLabel")} description={t("webhookUrlDesc")}>
        <div className="flex min-w-0 max-w-[460px] items-center gap-1">
          <Truncate as="code" className="timecode max-w-[300px] text-xs text-muted-foreground">
            {revealed ? url : `${base}?secret=••••••`}
          </Truncate>
          <IconButton
            label={t("copy")}
            disabled={!revealed}
            disabledReason={revealed ? undefined : t("webhookSecretHidden")}
            onClick={() => copy(url, t("webhookCopied"))}
          >
            <Copy />
          </IconButton>
          <IconButton label={t("webhookReset")} disabled={!!ownerOnly} disabledReason={ownerOnly} onClick={() => setConfirming(true)}>
            <RotateCcw />
          </IconButton>
        </div>
      </SettingsRow>
      <div className="grid gap-2 pb-4">
        {revealed ? (
          <p data-webhook-secret-once="" className="m-0 rounded-md border border-[color-mix(in_srgb,var(--warning)_35%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_8%,transparent)] px-3 py-2 text-ui-xs leading-[1.5] text-foreground">
            {t("webhookSecretOnce")}
          </p>
        ) : task.webhook_secret_set_at ? (
          <small className="text-ui-xs leading-[1.5] text-muted-foreground">{t("webhookSecretHidden")}</small>
        ) : (
          <div data-webhook-secret-legacy="" className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-[color-mix(in_srgb,var(--warning)_35%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_8%,transparent)] px-3 py-2">
            <span className="text-ui-xs leading-[1.5] text-foreground">
              {task.is_mine ? t("webhookLegacySecret") : t("webhookLegacySecretNotMine")}
            </span>
            {task.is_mine && (
              <Button size="xs" variant="outline" onClick={() => setConfirming(true)}>
                <RotateCcw size={12} /> {t("webhookReset")}
              </Button>
            )}
          </div>
        )}
        <button
          type="button"
          className="inline-flex w-fit items-center gap-1 text-ui-xs text-muted-foreground hover:text-foreground"
          aria-expanded={showApi}
          onClick={() => setShowApi(!showApi)}
        >
          <ChevronRight size={13} className={cn("transition-transform", showApi && "rotate-90")} aria-hidden="true" />
          {t("webhookApiToggle")}
        </button>
        {showApi && (
          <div className="grid gap-2 rounded-md bg-muted/50 p-3">
            {calls.map(([label, command]) => (
              <div key={label} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 gap-y-0.5">
                <span className="col-span-2 text-ui-xs text-muted-foreground">{label}</span>
                <Truncate as="code" className="timecode text-xs text-foreground">{command}</Truncate>
                <IconButton size="icon-xs" label={`${t("copy")}: ${label}`} onClick={() => copy(command, t("webhookApiCopied"))}>
                  <Copy />
                </IconButton>
              </div>
            ))}
            <small className="text-ui-xs text-muted-foreground">{t("webhookApiStatuses")}</small>
          </div>
        )}
      </div>
      <ConfirmDialog
        open={confirming}
        title={t("webhookResetTitle")}
        body={t("webhookResetBody")}
        confirmLabel={t("webhookReset")}
        onCancel={() => setConfirming(false)}
        pending={reset.isPending}
        onConfirm={() => reset.mutate()}
      />
    </div>
  );
}

/** 任务详情里的"这个任务做什么":显示绑定的工作流。取数在这里,怎么画在 boundWorkflowRow。 */
function BoundWorkflowRow({ task, workspaceId }: { task: ScheduledTask; workspaceId: string }) {
  const workflows = useWorkflows(workspaceId);
  return (
    <BoundWorkflowRowView
      workflowId={boundWorkflowId(task)}
      workflows={workflows.data ?? []}
      isPending={workflows.isPending}
    />
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
  //: 工作流开始节点的参数(见 taskParams):换了工作流就从头填。
  const [paramValues, setParamValues] = React.useState<Record<string, string>>({});
  const [attempted, setAttempted] = React.useState(false);

  const workflows = useQuery({
    queryKey: ["workflows", workspace.id],
    queryFn: () => listWorkflows(workspace.id),
    enabled: open,
  });
  const selectedWorkflow = (workflows.data ?? []).find((workflow) => workflow.id === workflowId) ?? null;
  const specs = React.useMemo(() => startParamsOf(selectedWorkflow?.graph), [selectedWorkflow]);
  const missing = missingRequired(specs, paramValues);

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
        //: 「每天 09:00」是**这个人这里**的 09:00:不带时区的话后端按 UTC 算,北京时间下午五点才跑(体检 UM-18)。
        timezone: localTimeZone(),
        payload: { workflow_id: workflowId, params: runParamsFrom(specs, paramValues) },
      });
    },
    onSuccess: onCreated,
    //: 跑不起来的原因(缺参数、工作流里还有没填的节点)写在弹窗里、挨着要改的地方,不只是右下角一闪而过。
    onError: () => undefined,
  });
  const submit = () => {
    setAttempted(true);
    if (missing.length > 0) return;
    create.mutate();
  };

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title={t("createTask")}
      footer={
        <>
          <Button variant="outline" size="sm" onClick={onClose}>{t("cancel")}</Button>
          <Button size="sm" disabled={!workflowId} loading={create.isPending} onClick={submit}>
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
            onValueChange={(next) => {
              setWorkflowId(next);
              setParamValues({});
              setAttempted(false);
              create.reset();
            }}
          />
          {(workflows.data ?? []).length === 0 && workflows.isSuccess && (
            <small>{t("noWorkflowHint")}</small>
          )}
          {selectedWorkflow?.description && (
            <small>
              <InlineMarkdown text={selectedWorkflow.description} />
            </small>
          )}
        </div>
        <TaskParamsForm specs={specs} values={paramValues} onChange={setParamValues} showMissing={attempted} missing={missing} />
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
            <div className="flex gap-1.5 [&>button]:min-w-0 [&>button]:flex-1">
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
                // 和左边的下拉同一种触发器(见 TimePicker):原生 time 控件的框和拨盘都不吃表单样式。
                <TimePicker
                  className="w-[128px] flex-none"
                  ariaLabel={t("triggerDailyAt")}
                  value={dailyTime}
                  onChange={setDailyTime}
                />
              )}
            </div>
          </div>
        )}
        {create.isError && (
          <p role="alert" className="m-0 text-ui-xs leading-[1.5] text-destructive">{errorText(create.error)}</p>
        )}
      </div>
    </ModalShell>
  );
}

function TaskDetail({
  task,
  workspaceId,
  revealedSecret,
  onSecretIssued,
}: {
  task: ScheduledTask;
  workspaceId: string;
  revealedSecret?: string;
  onSecretIssued: (task: ScheduledTask) => void;
}) {
  const t = useI18n();
  //: 管这个任务只有它的主人(后端 scheduler.manageable_task):它到点替主人跑、用主人的钥匙和额度。
  const ownerOnly = task.is_mine ? undefined : t("taskOwnerOnly");
  const qc = useQueryClient();
  const [deleting, setDeleting] = React.useState(false);

  const runs = useQuery(taskRunsQuery(task.id));
  // 冒出一条新运行(或最新那条变了状态)时,顶上的「上次运行 / 下次运行」也要跟着换。
  const newest = runs.data?.[0];
  const newestKey = newest ? `${newest.id}:${newest.status}` : "";
  React.useEffect(() => {
    if (newestKey) void qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspaceId] });
  }, [newestKey, qc, workspaceId]);
  // 和任务中心读**同一份**(同一个键、同一种取法)。运行记录的 job 是包装任务,本来就是顶层的。
  const jobsQuery = topLevelJobsQuery(workspaceId);
  const jobs = useQuery(jobsQuery);
  const isBlocked = useIsBlocked(workspaceId);
  const blocked = isBlocked(task);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspaceId] });
    void qc.invalidateQueries({ queryKey: ["task-runs", task.id] });
  };
  const toggleTask = useMutation({
    mutationFn: (enabled: boolean) => updateScheduledTask(task.id, { enabled }),
    onSuccess: refresh,
  });
  const localZone = localTimeZone();
  const useLocalZone = useMutation({
    mutationFn: () => updateScheduledTask(task.id, { timezone: localZone }),
    onSuccess: refresh,
  });
  const runTask = useMutation({
    mutationFn: () => runScheduledTask(task.id),
    onSuccess: () => {
      refresh();
      void qc.invalidateQueries({ queryKey: jobsQuery.queryKey });
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

  // 按本地时区、当前语言给人读。
  const formatTime = (iso: string) =>
    parseServerTime(iso).toLocaleString(locale, {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    });
  const localTime = (iso: string | null | undefined) => (iso ? formatTime(iso) : null);
  // 计划 / 下次运行按触发方式说人话,见 scheduleText。
  const scheduleLabel = scheduleText(task, t, locale, formatTime);

  return (
    <div className="grid w-full min-w-0 content-start gap-6">
      {/* **页头,不是卡片。** 任务名是这一页的身份 —— 它此前和运行记录一样是个 SettingsGroup,
          两块等重,而真正天天看的是下面那份记录。 */}
      <header className="grid gap-5 border-b border-divider pb-5">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <Truncate as="h2" className="m-0 text-xl font-semibold text-foreground">{task.name}</Truncate>
          <TaskRunControls
            enabled={task.enabled}
            blocked={blocked}
            notOwner={ownerOnly}
            // 按**这个任务实际有没有一次在跑**判,和工作流编辑器的运行键同一个意思;请求那几十毫秒也算。
            running={runTask.isPending || hasActiveRun(runs.data)}
            onRun={() => runTask.mutate()}
            onToggle={(checked) => toggleTask.mutate(checked)}
          />
        </div>
        {/* 计划 / 下次 / 上次是**三个短事实**,不是三件要操作的事 —— 它们此前各占一整行,
            每行还配一句说明,读三个时间戳要扫过六行字。摆成一排。 */}
        <dl className="m-0 grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-4 text-ui-xs [&_dd]:m-0 [&_dd]:text-foreground [&_dt]:text-muted-foreground">
          <div className="grid min-w-0 content-start gap-1.5 [&_dd]:text-ui-sm [&_dd]:break-words">
            <dt>{t("taskSchedule")}</dt>
            <dd className="tabular-nums">{scheduleLabel}</dd>
            {/* 「每天 09:00」是哪里的 09:00:和这台电脑不是同一个时区时写出来(老任务都是 UTC),主人能一键改成本地。 */}
            {scheduleUsesClock(task) && task.timezone !== localZone && (
              <dd data-task-timezone="" className="flex flex-wrap items-center gap-1.5 text-ui-xs text-muted-foreground">
                {t("taskTimezoneOther").replace("{zone}", task.timezone)}
                {task.is_mine && (
                  <Button size="xs" variant="outline" loading={useLocalZone.isPending} onClick={() => useLocalZone.mutate()}>
                    {t("taskTimezoneUseLocal").replace("{zone}", localZone)}
                  </Button>
                )}
              </dd>
            )}
          </div>
          <div className="grid min-w-0 content-start gap-1.5 [&_dd]:text-ui-sm [&_dd]:break-words">
            <dt>{t("taskNextRun")}</dt>
            <dd className="tabular-nums">{nextRunText(task, t, formatTime)}</dd>
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
          {task.kind === "workflow" && <TaskParamsRow task={task} workspaceId={workspaceId} />}
          {task.trigger_type === "webhook" && (
            <WebhookUrlRow task={task} workspaceId={workspaceId} revealed={revealedSecret} onSecretIssued={onSecretIssued} />
          )}
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
        <Hint disabledReason={ownerOnly}>
          <Button
            size="sm"
            variant="ghost"
            className="shrink-0 text-muted-foreground hover:text-destructive"
            disabled={!!ownerOnly}
            onClick={() => setDeleting(true)}
          >
            <Trash2 size={13} /> {t("delete")}
          </Button>
        </Hint>
      </div>

      <ConfirmDialog
        open={deleting}
        title={t("deleteConfirmTitle")}
        body={t("deleteTaskBody")}
        onCancel={() => setDeleting(false)}
        pending={deleteTask.isPending}
        onConfirm={() => deleteTask.mutate()}
      />
    </div>
  );
}

/** 一次运行开始的钟点:本地时区、当前语言,月-日 时:分:秒。 */
function runClock(iso: string, locale: string): string {
  return parseServerTime(iso).toLocaleString(locale, {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });
}

/**
 * 任务带给工作流的参数(开始节点那几项,见 taskParams):看得到填了什么;主人能改。
 *
 * 此前新建弹窗没地方填、参数写死成 `{}`,工作流只要有一个必填输入就建不成;建好的任务也改不了参数(体检 UM-03)。
 */
function TaskParamsRow({ task, workspaceId }: { task: ScheduledTask; workspaceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const workflows = useWorkflows(workspaceId);
  const workflow = (workflows.data ?? []).find((one) => one.id === boundWorkflowId(task)) ?? null;
  const specs = React.useMemo(() => startParamsOf(workflow?.graph), [workflow]);
  const saved = (task.payload as { params?: unknown })?.params;
  const [editing, setEditing] = React.useState(false);
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [attempted, setAttempted] = React.useState(false);
  const missing = missingRequired(specs, values);
  const save = useMutation({
    mutationFn: () => updateScheduledTask(task.id, { payload: { ...task.payload, params: runParamsFrom(specs, values) } }),
    onSuccess: () => {
      setEditing(false);
      void qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspaceId] });
    },
    onError: () => undefined,
  });
  if (!workflow || specs.length === 0) return null;
  const shown = formValuesFrom(specs, saved);
  const startEditing = () => {
    setValues(shown);
    setAttempted(false);
    save.reset();
    setEditing(true);
  };
  return (
    <div className="grid gap-2 py-4" data-task-params-row="">
      {editing ? (
        <>
          <TaskParamsForm specs={specs} values={values} onChange={setValues} showMissing={attempted} missing={missing} />
          {save.isError && <p role="alert" className="m-0 text-ui-xs leading-[1.5] text-destructive">{errorText(save.error)}</p>}
          <div className="flex gap-1.5">
            <Button
              size="sm"
              loading={save.isPending}
              onClick={() => {
                setAttempted(true);
                if (missing.length === 0) save.mutate();
              }}
            >
              {t("taskParamsSave")}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setEditing(false)}>{t("cancel")}</Button>
          </div>
        </>
      ) : (
        <SettingsRow label={t("taskParamsLabel")} description={t("taskParamsDesc")}>
          <div className="flex min-w-0 max-w-[460px] items-start gap-2">
            <dl className="m-0 grid min-w-0 flex-1 grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-ui-xs [&_dd]:m-0">
              {specs.map((spec) => (
                <React.Fragment key={spec.name}>
                  <dt className="text-muted-foreground">{spec.name}</dt>
                  <Truncate as="dd" className={cn(!shown[spec.name] && "text-muted-foreground")}>
                    {shown[spec.name] || (spec.fallback === "" || spec.fallback == null ? "—" : t("taskParamDefaultPlaceholder").replace("{value}", String(spec.fallback)))}
                  </Truncate>
                </React.Fragment>
              ))}
            </dl>
            <Hint disabledReason={task.is_mine ? undefined : t("taskOwnerOnly")}>
              <Button size="xs" variant="outline" disabled={!task.is_mine} onClick={startEditing}>
                {t("taskParamsEdit")}
              </Button>
            </Hint>
          </div>
        </SettingsRow>
      )}
    </div>
  );
}

function RunRow({ run, job }: { run: ScheduledTaskRun; job: JobSummary | null }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const running = run.status === "queued" || run.status === "running";
  // 耗时:两端都有才算;运行中显示已流逝。
  const seconds = elapsedSecondsBetween(run.started_at, run.finished_at ?? new Date());
  const durationText = seconds == null ? null : formatElapsedSeconds(seconds);
  const message = run.error ?? (running ? job?.message : null);
  const attest = run.status === "failed" ? attestRequestOf((run.result as Record<string, unknown> | undefined)?.attest) : null;
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
        ) : run.status === "cancelled" ? (
          <Ban size={12} />
        ) : (
          <CircleAlert size={12} />
        )}
      </span>
      <div className="grid min-w-0 flex-1 gap-px">
        <div className="flex min-w-0 items-baseline gap-1.5 [&_strong]:whitespace-nowrap [&_strong]:text-ui-sm">
          <strong>{run.started_at ? relativeTime(run.started_at, locale) : runStatusText(t, run.status)}</strong>
          {run.started_at && (
            //: 按本地时区显示,和页头「上次运行」同一个钟:此前直接截了后端的 UTC 字符串,北京时间差 8 小时(体检 UM-18)。
            <span className="timecode text-ui-xs text-muted-foreground">{runClock(run.started_at, locale)}</span>
          )}
        </div>
        {message && (
          <Truncate as="small" className="text-ui-xs text-muted-foreground">
            {message}
          </Truncate>
        )}
      </div>
      {/* 停在「这一版工作流是别人改的,要主人认可」:认可那一版之后,下次运行就借得到了。 */}
      {attest && <AttestRevisionButton attest={attest} />}
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
        {runStatusText(t, running ? "running" : run.status)}
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
