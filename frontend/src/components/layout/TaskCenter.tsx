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

const ACTIVE = new Set(["queued", "running"]);

/** 任务总线的统一入口(计划 §12 / Phase 6):导出、转写、AI 生成、
 * 定时任务都在这一个面板里看进度;刷新后从 /api/jobs 直接恢复。 */
export function TaskCenter({ workspaceId }: { workspaceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(false);
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
              size="icon-sm"
              className="taskcenter-btn"
              aria-label={t("taskCenter")}
            >
              {active.length > 0 ? <Loader2 size={15} className="spin" /> : <Activity size={15} />}
              {active.length > 0 && <em className="taskcenter-badge">{active.length}</em>}
            </Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>{t("taskCenter")}</TooltipContent>
      </Tooltip>

      <PopoverContent className="taskcenter-pop" aria-label={t("taskCenter")}>
        <div className="taskcenter-head">
          <strong>{t("taskCenter")}</strong>
          {finished.length > 0 && (
            <button
              type="button"
              className="taskcenter-clear"
              disabled={clearFinished.isPending}
              onClick={() => clearFinished.mutate()}
            >
              <Trash2 size={11} /> {t("clearFinished")}
            </button>
          )}
        </div>
        <div className="taskcenter-list">
          {active.map((job) => (
            <JobRow key={job.id} job={job} onOpen={() => openJob(job)} onCancel={() => cancelJob.mutate(job.id)} />
          ))}
          {active.length > 0 && finished.length > 0 && <div className="taskcenter-sep" />}
          {finished.map((job) => (
            <JobRow key={job.id} job={job} onOpen={() => openJob(job)} />
          ))}
          {all.length === 0 && <p className="taskcenter-empty">{t("noJobs")}</p>}
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
  return (
    <div
      className={running ? "taskrow running clickable" : `taskrow ${job.status} clickable`}
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter") onOpen?.();
      }}
    >
      <span className="taskrow-icon">{meta.icon}</span>
      <div className="taskrow-body">
        <div className="taskrow-title">
          <strong>{t(meta.labelKey as never)}</strong>
          <span className="taskrow-status">
            {job.status === "succeeded" ? (
              <CheckCircle2 size={12} className="inv-ok" />
            ) : job.status === "failed" ? (
              <CircleAlert size={12} className="inv-bad" />
            ) : (
              `${Math.round(job.progress * 100)}%`
            )}
            {running && onCancel && (
              <button
                type="button"
                className="taskrow-cancel"
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
        {running && <Progress className="taskrow-progress" value={Math.round(job.progress * 100)} />}
        <small className="taskrow-msg" title={job.error ?? job.message}>
          {job.status === "failed" ? (job.error ?? job.message) : job.message}
        </small>
      </div>
    </div>
  );
}
