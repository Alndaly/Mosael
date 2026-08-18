import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, CheckCircle2, CircleAlert, Download, GitBranch, ListChecks, Loader2, Mic, Send, Sparkles, Timer, Trash2, X } from "lucide-react";

import { toast } from "sonner";

import { api, type Job } from "@/api/client";
import { EmptyState } from "@/components/layout/EmptyState";
import { useI18n } from "@/app/preferences";
import { JobDetailDialog } from "@/components/layout/JobDetailDialog";
import { gotoRecord } from "@/lib/deepLink";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Progress } from "@/components/ui/progress";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const ACTIVE = new Set(["queued", "running"]);

/** 任务总线的统一入口(计划 §12 / Phase 6):导出、转写、AI 生成、
 * 定时任务都在这一个面板里看进度;刷新后从 /api/jobs 直接恢复。 */
export function TaskCenter({ workspaceId }: { workspaceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(false);
  // 深链通道(与 openstudio:open-* 约定一致):首页任务磁贴等入口用事件打开任务中心弹层。
  React.useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener("openstudio:open-tasks", onOpen);
    return () => window.removeEventListener("openstudio:open-tasks", onOpen);
  }, []);
  const [detailJob, setDetailJob] = React.useState<Job | null>(null);

  const jobs = useQuery({
    queryKey: ["jobs", workspaceId, "all"],
    // top_level=true:工作流派生的子任务(发布/导出/转写/生成/配音)收纳到父工作流下,
    // 不再与父工作流平铺成两行;子任务在工作流任务详情里查看。
    queryFn: () => api<Job[]>(`/api/jobs?workspace_id=${workspaceId}&top_level=true`),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((job) => ACTIVE.has(job.status)) ? 1500 : 8000,
    refetchOnWindowFocus: true,
  });
  const clearFinished = useMutation({
    mutationFn: () => api(`/api/jobs/finished?workspace_id=${workspaceId}`, { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["jobs", workspaceId, "all"] }),
  });
  const cancelJob = useMutation({
    mutationFn: (jobId: string) => api(`/api/jobs/${jobId}/cancel`, { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["jobs", workspaceId, "all"] }),
    onError: (error: Error) => toast.error(error.message),
  });

  const all = jobs.data ?? [];
  const active = all.filter((job) => ACTIVE.has(job.status));
  const finished = all.filter((job) => !ACTIVE.has(job.status)).slice(0, 12);

  // 点任务行 → 打开该 job 的执行详情弹层(状态 + 事件时间线)。
  const openJob = (job: Job) => {
    setDetailJob(job);
    setOpen(false);
  };

  // 详情弹层里「前往对应页面」:发布/工作流/批量都直达对应的那条记录,其余到业务页。
  const gotoJobPage = (job: Job) => {
    const route = jobRoute(job);
    if (!route) return;
    const payload = (job.payload ?? {}) as Record<string, unknown>;
    if (job.kind === "publish") gotoRecord(route, "openstudio:open-publish-task", payload.task_id);
    else if (job.kind === "workflow") gotoRecord(route, "openstudio:open-workflow", payload.workflow_id);
    else gotoRecord(route);
    setDetailJob(null);
  };

  // 把「有几个任务在跑」推给桌面端(托盘文案 + 有任务时阻止系统睡眠)。放这里是因为这个组件
  // 本来就在按活跃度自适应轮询 /api/jobs,不必为此再拉一个查询;也因为方向必须是「知道业务的
  // 这一侧告诉系统层」,而不是让主进程反过来查后端。
  // 进度取活跃任务的均值:Windows 任务栏进度条要一个 0..1。都还没报进度(全 0)时给 null,
  // 让系统层走不确定态 —— 显示 0% 会看起来像卡住了,而它其实只是还没开始报。
  const aggregateProgress = React.useMemo(() => {
    if (active.length === 0) return null;
    const sum = active.reduce((acc, job) => acc + (typeof job.progress === "number" ? job.progress : 0), 0);
    return sum > 0 ? sum / active.length : null;
  }, [active]);
  React.useEffect(() => {
    window.openStudioDesktop?.reportStatus?.({ runningJobs: active.length, progress: aggregateProgress });
  }, [active.length, aggregateProgress]);

  // 任务完成提示:只在「上一轮还在跑、这一轮结束了」的跃迁上弹一次,
  // 首次加载时只记录基线,避免刷新后把历史任务全部弹一遍。
  const prevStatuses = React.useRef<Map<string, string> | null>(null);
  // Reset the baseline when the workspace changes. Neither TaskCenter nor Studio is keyed, so
  // this ref survived the switch; the new workspace's jobs then all hit `prev === undefined`
  // and the "first seen already terminal" branch below toasted every one of them — a wall of
  // notifications for jobs that finished days ago, which is precisely what the baseline exists
  // to prevent.
  React.useEffect(() => {
    prevStatuses.current = null;
  }, [workspaceId]);
  React.useEffect(() => {
    if (!jobs.data) return;
    if (prevStatuses.current === null) {
      prevStatuses.current = new Map(jobs.data.map((job) => [job.id, job.status]));
      return;
    }
    for (const job of jobs.data) {
      const prev = prevStatuses.current.get(job.id);
      const terminal = job.status === "succeeded" || job.status === "failed";
      // Toast on active→terminal, AND when a job first appears already terminal (prev undefined).
      // A fast job (e.g. a workflow with a notify node) can go queued→done between two polls, so
      // it's never seen active — without this it would silently skip its completion toast.
      const shouldToast = terminal && (prev === undefined || ACTIVE.has(prev));
      if (shouldToast) {
        // **任务做完了,它改动的东西就得跟着刷新。** 此前这里只弹一句 toast:从链接下完的
        // 视频不会出现在素材库,渲染产出、配音产出同理 —— 都要用户自己刷新页面才看得见,
        // 而"任务完成"的提示就在眼前。逐个页面各自轮询是同一件事写十遍,所以放在这里一处:
        // 任务中心本来就是唯一知道"哪个任务刚变成完成态"的地方。
        if (job.status === "succeeded") {
          for (const key of TOUCHES[job.kind] ?? DEFAULT_TOUCHES) {
            void qc.invalidateQueries({ queryKey: [key] });
          }
        }
        const label = t((KIND_META[job.kind]?.labelKey ?? "jobKindOther") as never);
        if (job.status === "succeeded") toast.success(`${label} · ${t("jobDone")}`);
        else toast.error(`${label} · ${t("jobFailed")}`, { description: job.error ?? undefined });
        // 同一件事也告诉系统层。这里无条件调用、由主进程决定发不发:窗口收进托盘或切到别的
        // app 时,上面这个 toast 弹在一个看不见的窗口里等于没弹,那时才需要系统通知。
        window.openStudioDesktop?.notifyTask?.({
          title: `${label} · ${job.status === "succeeded" ? t("jobDone") : t("jobFailed")}`,
          body: job.error ?? job.message ?? "",
        });
      }
      prevStatuses.current.set(job.id, job.status);
    }
  }, [jobs.data, t, qc]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="relative"
              aria-label={t("taskCenter")}
            >
              {active.length > 0 ? <Loader2 size={15} className="animate-openstudio-spin" /> : <Activity size={15} />}
              {active.length > 0 && <em className="absolute -top-0.5 right-[-3px] h-3.5 min-w-3.5 rounded-full bg-primary px-[3px] text-center text-[9.5px] font-bold not-italic leading-[14px] text-primary-foreground">{active.length}</em>}
            </Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>{t("taskCenter")}</TooltipContent>
      </Tooltip>

      <PopoverContent className="w-[340px] overflow-hidden" aria-label={t("taskCenter")}>
        <div className="flex items-center justify-between border-b border-border px-2.5 py-2 [&_strong]:text-ui-sm">
          <strong>{t("taskCenter")}</strong>
          {finished.length > 0 && (
            <button
              type="button"
              className="inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent text-ui-xs text-muted-foreground hover:text-destructive"
              disabled={clearFinished.isPending}
              onClick={() => clearFinished.mutate()}
            >
              <Trash2 size={11} /> {t("clearFinished")}
            </button>
          )}
        </div>
        <div className="grid max-h-[380px] gap-1 overflow-y-auto p-1.5">
          {active.map((job) => (
            <JobRow key={job.id} job={job} onOpen={() => openJob(job)} onCancel={() => cancelJob.mutate(job.id)} />
          ))}
          {active.length > 0 && finished.length > 0 && <div className="mx-1.5 my-1 h-px bg-border" />}
          {finished.map((job) => (
            <JobRow key={job.id} job={job} onOpen={() => openJob(job)} />
          ))}
          {all.length === 0 && (
            <EmptyState size="compact" icon={<ListChecks size={15} />} title={t("noJobsTitle")} body={t("noJobs")} />
          )}
        </div>
      </PopoverContent>
      <JobDetailDialog
        job={detailJob}
        onClose={() => setDetailJob(null)}
        onGoto={detailJob && jobRoute(detailJob) ? () => gotoJobPage(detailJob) : undefined}
      />
    </Popover>
  );
}

/** 某种任务做完后,可能被它改动过的查询。
 *
 * **默认就含 assets**(见 DEFAULT_TOUCHES):绝大多数任务的产物都落进素材库,而漏掉一个 kind
 * 的代价是"做完了却要刷新页面才看得见"。新增任务类型时不写这张表也是对的,写了才是更准。 */
const TOUCHES: Record<string, string[]> = {
  url_import: ["assets"],
  render: ["assets", "sequences"],
  subtitle_dub: ["assets", "sequences"],
  transcribe: ["assets", "transcript"],
  workflow: ["assets", "sequences", "workflows"],
  publish: ["publish-tasks"],
  ai_generation: ["assets", "generation-jobs", "generation-sessions"],
};

const DEFAULT_TOUCHES = ["assets"];

const KIND_META: Record<string, { icon: React.ReactNode; labelKey: string }> = {
  render: { icon: <Download size={13} />, labelKey: "jobKindRender" },
  transcribe: { icon: <Mic size={13} />, labelKey: "jobKindTranscribe" },
  ai_generation: { icon: <Sparkles size={13} />, labelKey: "jobKindGeneration" },
  scheduled: { icon: <Timer size={13} />, labelKey: "jobKindScheduled" },
  workflow: { icon: <GitBranch size={13} />, labelKey: "jobKindWorkflow" },
  publish: { icon: <Send size={13} />, labelKey: "jobKindPublish" },
};

/** 任务 → 对应详情页;payload 里有 project_id 就带上,编辑器直接落到项目。 */
const KIND_ROUTE: Record<string, string> = {
  render: "editor",
  transcribe: "editor",
  ai_generation: "ai",
  scheduled: "scheduler",
  workflow: "workflows",
  publish: "publish",
};

function jobRoute(job: Job): string | null {
  const view = KIND_ROUTE[job.kind];
  if (!view) return null;
  const projectId = ((job.payload ?? {}) as Record<string, unknown>).project_id;
  return `/${view}${typeof projectId === "string" && projectId ? `?p=${projectId}` : ""}`;
}

function JobRow({ job, onOpen, onCancel }: { job: Job; onOpen?: () => void; onCancel?: () => void }) {
  const t = useI18n();
  const meta = KIND_META[job.kind] ?? { icon: <Activity size={13} />, labelKey: "jobKindOther" };
  const running = ACTIVE.has(job.status);
  const failed = !running && job.status === "failed";
  return (
    <div
      className="grid cursor-pointer grid-cols-[26px_minmax(0,1fr)] items-start gap-1.5 rounded-md px-1.5 py-[7px] hover:bg-secondary"
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter") onOpen?.();
      }}
    >
      <span
        className={cn(
          "grid h-[26px] w-[26px] place-items-center rounded-md bg-accent text-accent-foreground",
          failed && "bg-[color-mix(in_oklab,var(--destructive)_12%,var(--background))] text-destructive",
        )}
      >
        {meta.icon}
      </span>
      <div className="grid min-w-0 gap-[3px]">
        <div className="flex items-center justify-between gap-1.5 [&_strong]:text-xs [&_strong]:font-semibold">
          <strong>{t(meta.labelKey as never)}</strong>
          <span className="inline-flex items-center text-ui-2xs tabular-nums text-muted-foreground">
            {job.status === "succeeded" ? (
              <CheckCircle2 size={12} className="text-[#16a34a]" />
            ) : job.status === "failed" ? (
              <CircleAlert size={12} className="text-destructive" />
            ) : (
              `${Math.round(job.progress * 100)}%`
            )}
            {running && onCancel && (
              <button
                type="button"
                className="ml-[3px] inline-grid h-4 w-4 cursor-pointer place-items-center rounded-sm border-0 bg-transparent text-muted-foreground hover:bg-secondary hover:text-destructive"
                title={t("jobCancel")}
                aria-label={t("jobCancel")}
                onClick={(event) => {
                  event.stopPropagation();
                  onCancel();
                }}
              >
                <X size={11} />
              </button>
            )}
          </span>
        </div>
        {running && <Progress value={Math.round(job.progress * 100)} />}
        <small className={cn("truncate text-ui-xs text-muted-foreground", failed && "text-destructive")} title={job.error ?? job.message}>
          {job.status === "failed" ? (job.error ?? job.message) : job.message}
        </small>
      </div>
    </div>
  );
}
