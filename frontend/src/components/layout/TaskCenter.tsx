import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  CheckCircle2,
  CircleAlert,
  Download,
  GitBranch,
  Layers,
  Loader2,
  Mic,
  Send,
  Sparkles,
  Timer,
  Trash2,
  X,
} from "lucide-react";

import { toast } from "sonner";

import { api, type Job } from "@/api/client";
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
  // 深链通道(与 mibu:open-* 约定一致):首页任务磁贴等入口用事件打开任务中心弹层。
  React.useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener("mibu:open-tasks", onOpen);
    return () => window.removeEventListener("mibu:open-tasks", onOpen);
  }, []);
  const [detailJob, setDetailJob] = React.useState<Job | null>(null);

  const jobs = useQuery({
    queryKey: ["jobs", workspaceId, "all"],
    queryFn: () => api<Job[]>(`/api/jobs?workspace_id=${workspaceId}`),
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
    if (job.kind === "publish") gotoRecord(route, "mibu:open-publish-task", payload.task_id);
    else if (job.kind === "batch" || typeof payload.batch_id === "string")
      gotoRecord("/batch", "mibu:open-batch", payload.batch_id);
    else if (job.kind === "workflow") gotoRecord(route, "mibu:open-workflow", payload.workflow_id);
    else gotoRecord(route);
    setDetailJob(null);
  };

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
        const label = t((KIND_META[job.kind]?.labelKey ?? "jobKindOther") as never);
        if (job.status === "succeeded") toast.success(`${label} · ${t("jobDone")}`);
        else toast.error(`${label} · ${t("jobFailed")}`, { description: job.error ?? undefined });
      }
      prevStatuses.current.set(job.id, job.status);
    }
  }, [jobs.data, t]);

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
              {active.length > 0 ? <Loader2 size={15} className="animate-mibu-spin" /> : <Activity size={15} />}
              {active.length > 0 && <em className="absolute -top-0.5 right-[-3px] h-3.5 min-w-3.5 rounded-full bg-primary px-[3px] text-center text-[9.5px] font-bold not-italic leading-[14px] text-primary-foreground">{active.length}</em>}
            </Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>{t("taskCenter")}</TooltipContent>
      </Tooltip>

      <PopoverContent className="w-[340px] overflow-hidden" aria-label={t("taskCenter")}>
        <div className="flex items-center justify-between border-b border-border px-2.5 py-2 [&_strong]:text-[12.5px]">
          <strong>{t("taskCenter")}</strong>
          {finished.length > 0 && (
            <button
              type="button"
              className="inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent text-[11px] text-muted-foreground hover:text-destructive"
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
          {all.length === 0 && <p className="m-0 px-3 py-[18px] text-center text-xs leading-[1.6] text-muted-foreground">{t("noJobs")}</p>}
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

const KIND_META: Record<string, { icon: React.ReactNode; labelKey: string }> = {
  render: { icon: <Download size={13} />, labelKey: "jobKindRender" },
  transcribe: { icon: <Mic size={13} />, labelKey: "jobKindTranscribe" },
  ai_generation: { icon: <Sparkles size={13} />, labelKey: "jobKindGeneration" },
  scheduled: { icon: <Timer size={13} />, labelKey: "jobKindScheduled" },
  workflow: { icon: <GitBranch size={13} />, labelKey: "jobKindWorkflow" },
  publish: { icon: <Send size={13} />, labelKey: "jobKindPublish" },
  batch: { icon: <Layers size={13} />, labelKey: "jobKindBatch" },
};

/** 任务 → 对应详情页;payload 里有 project_id 就带上,编辑器直接落到项目。 */
const KIND_ROUTE: Record<string, string> = {
  render: "editor",
  transcribe: "editor",
  ai_generation: "ai",
  scheduled: "scheduler",
  workflow: "workflows",
  publish: "publish",
  batch: "batch",
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
          <span className="inline-flex items-center text-[10.5px] tabular-nums text-muted-foreground">
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
        <small className={cn("truncate text-[11px] text-muted-foreground", failed && "text-destructive")} title={job.error ?? job.message}>
          {job.status === "failed" ? (job.error ?? job.message) : job.message}
        </small>
      </div>
    </div>
  );
}
