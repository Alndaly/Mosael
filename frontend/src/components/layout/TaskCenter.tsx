import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  CheckCircle2,
  CircleAlert,
  Download,
  Loader2,
  Mic,
  Sparkles,
  Timer,
  Trash2,
} from "lucide-react";

import { api, type Job } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
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

  const all = jobs.data ?? [];
  const active = all.filter((job) => ACTIVE.has(job.status));
  const finished = all.filter((job) => !ACTIVE.has(job.status)).slice(0, 12);

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
            <JobRow key={job.id} job={job} />
          ))}
          {active.length > 0 && finished.length > 0 && <div className="taskcenter-sep" />}
          {finished.map((job) => (
            <JobRow key={job.id} job={job} />
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
};

function JobRow({ job }: { job: Job }) {
  const t = useI18n();
  const meta = KIND_META[job.kind] ?? { icon: <Activity size={13} />, labelKey: "jobKindOther" };
  const running = ACTIVE.has(job.status);
  return (
    <div className={running ? "taskrow running" : `taskrow ${job.status}`}>
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
          </span>
        </div>
        {running && (
          <div className="taskrow-progress">
            <div className="taskrow-progress-fill" style={{ width: `${Math.max(3, job.progress * 100)}%` }} />
          </div>
        )}
        <small className="taskrow-msg" title={job.error ?? job.message}>
          {job.status === "failed" ? (job.error ?? job.message) : job.message}
        </small>
      </div>
    </div>
  );
}
