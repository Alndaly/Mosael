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

  const jobs = useQuery({
    queryKey: ["jobs", workspaceId, "all"],
    queryFn: () => api<Job[]>(`/api/jobs?workspace_id=${workspaceId}`),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((job) => ACTIVE.has(job.status)) ? 1500 : 8000,
    refetchIntervalInBackground: true,
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

  const openJob = (job: Job) => {
    const route = jobRoute(job);
    if (!route) return;
    window.location.hash = route;
    // 发布任务直达那条发布记录:导航落定后经深链事件通道选中详情
    // (hash 会被路由归一化,query 传参不可靠)。
    const taskId = ((job.payload ?? {}) as Record<string, unknown>).task_id;
    if (job.kind === "publish" && typeof taskId === "string") {
      window.setTimeout(
        () => window.dispatchEvent(new CustomEvent("mibu:open-publish-task", { detail: taskId })),
        80,
      );
    }
    setOpen(false);
  };

  // 任务完成提示:只在「上一轮还在跑、这一轮结束了」的跃迁上弹一次,
  // 首次加载时只记录基线,避免刷新后把历史任务全部弹一遍。
  const prevStatuses = React.useRef<Map<string, string> | null>(null);
  React.useEffect(() => {
    if (!jobs.data) return;
    if (prevStatuses.current === null) {
      prevStatuses.current = new Map(jobs.data.map((job) => [job.id, job.status]));
      return;
    }
    for (const job of jobs.data) {
      const prev = prevStatuses.current.get(job.id);
      if (prev && ACTIVE.has(prev) && !ACTIVE.has(job.status)) {
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
