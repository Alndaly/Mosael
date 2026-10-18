import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CheckCircle2, ListChecks, Loader2, X } from "lucide-react";

import { cancelJob, topLevelJobsQuery, type JobSummary } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { InspectorCard } from "@/components/layout/InspectorCard";
import { JobDetailDialog } from "@/components/jobs/JobDetailDialog";
import { JobKindIcon, gotoJobPage, jobPage, useJobKinds } from "@/components/jobs/jobKinds";
import { runStatusText } from "@/components/jobs/runStatus";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { leaveNativeView } from "@/lib/nativeView";
import { formatElapsedSeconds } from "@/lib/time";
import { cn } from "@/lib/utils";

const ACTIVE = new Set(["queued", "running"]);

/** 任务载荷里「这份回执寄回哪次对话」那一块(见后端 receipts.receipt_to_session)。 */
function receiptSessionId(job: JobSummary): string | null {
  const payload = (job.payload ?? {}) as Record<string, unknown>;
  const receipt = payload.receipt as { session_id?: unknown } | undefined;
  return typeof receipt?.session_id === "string" ? receipt.session_id : null;
}

/**
 * 任务的名字。**生成任务优先读完整提示词**:`payload.subject` 现在存完整原文(旧任务可能只有前 80 字),
 * 而同一份 payload 的 `request.prompt` 一直是原文 —— 列表行要的是「是哪个任务」,不是一句断在 80 字
 * 处的谜语;放不下由 `Truncate` 收,不在这里切。
 */
function subjectOf(job: JobSummary, fallback: string): string {
  const payload = (job.payload ?? {}) as Record<string, unknown>;
  const request = payload.request as { prompt?: unknown } | undefined;
  const prompt = typeof request?.prompt === "string" ? request.prompt.trim() : "";
  if (prompt) return prompt;
  const subject = payload.subject;
  return typeof subject === "string" && subject.trim() ? subject.trim() : fallback;
}

/**
 * 右侧「本对话的后台任务」:这次对话发起的那些任务行 —— 跨轮次、跨重启,有进度、能取消、看得到结果。
 *
 * 它和下面的「最近工具」是两件事:那边是**每一次工具调用**(读一次文件、开一次浏览器都算,只留 6 条),
 * 这边是**任务行**(提交之后在后台跑、隔了几轮才结束的东西)。合成一块会把"它到底提交了什么"和
 * "它刚才读了什么"混成一列,两种东西的寿命和可操作性都不一样。
 *
 * 数据复用任务中心那份 `/api/jobs` 查询,在前端按 `payload.receipt.session_id` 过滤 —— 不为一个面板
 * 给接口加开关参数。轮询间隔也照任务中心:有在跑的 1.5 秒,没有的 8 秒。
 */
export function SessionJobsCard({ workspaceId, sessionId }: { workspaceId: string; sessionId: string | null }) {
  const t = useI18n();
  const qc = useQueryClient();
  const { kindOf } = useJobKinds();
  const [detailJob, setDetailJob] = React.useState<JobSummary | null>(null);

  const jobsQuery = React.useMemo(() => topLevelJobsQuery(workspaceId), [workspaceId]);
  const jobs = useQuery({
    ...jobsQuery,
    enabled: Boolean(sessionId),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((job) => ACTIVE.has(job.status)) ? 1500 : 8000,
  });

  const mine = React.useMemo(
    () => (jobs.data ?? []).filter((job) => receiptSessionId(job) === sessionId),
    [jobs.data, sessionId],
  );

  const cancel = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: jobsQuery.queryKey }),
  });

  if (!sessionId || mine.length === 0) return null;

  const detailKind = detailJob ? kindOf(detailJob.kind) : null;
  const detailPage = detailJob && detailKind ? jobPage(detailJob, detailKind) : null;

  return (
    <InspectorCard icon={ListChecks} title={t("chatJobsTitle")} aside={String(mine.length)}>
      <div className="grid min-w-0 gap-1.5" data-session-jobs="">
        <p className="m-0 text-ui-2xs leading-normal text-muted-foreground">{t("chatJobsScope")}</p>
        <ul className="m-0 grid list-none gap-1 p-0">
        {mine.map((job) => {
          const kind = kindOf(job.kind);
          const subject = subjectOf(job, kind.label);
          const active = ACTIVE.has(job.status);
          const failed = job.status === "failed";
          const page = jobPage(job, kind);
          const progress = typeof job.progress === "number" ? job.progress : 0;
          const elapsed = Math.max(0, (Date.now() - Date.parse(job.created_at)) / 1000);
          return (
            <li key={job.id} className="grid min-w-0 gap-0.5" data-session-job={job.id}>
              <div className="flex min-w-0 items-center gap-1">
                <Button
                  variant="ghost"
                  size="xs"
                  className="min-w-0 flex-1 justify-start gap-1.5"
                  onClick={() => setDetailJob(job)}
                >
                  <JobStatusIcon status={job.status} />
                  <JobKindIcon meta={kind} size={12} />
                  <span className="shrink-0 text-ui-2xs text-muted-foreground">{kind.label}</span>
                  <Truncate className="flex-1">{subject}</Truncate>
                  <span className="shrink-0 tabular-nums text-ui-2xs text-muted-foreground">
                    {active
                      ? progress > 0
                        ? `${Math.round(progress * 100)}%`
                        : t("chatJobsElapsed").replace("{t}", formatElapsedSeconds(elapsed))
                      : failed
                        ? null
                        : runStatusText(t, job.status)}
                  </span>
                </Button>
                {active ? (
                  <IconButton
                    size="icon-xs"
                    label={t("jobCancel")}
                    loading={cancel.isPending && cancel.variables === job.id}
                    onClick={() => cancel.mutate(job.id)}
                  >
                    <X size={12} />
                  </IconButton>
                ) : null}
                {failed && page ? (
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => {
                      void leaveNativeView();
                      gotoJobPage(job, kind);
                    }}
                  >
                    {t("chatJobsGoto")}
                  </Button>
                ) : null}
              </div>
              {failed && (job.error_summary || job.error) ? (
                <p className="m-0 min-w-0 pl-[18px] text-ui-2xs leading-normal text-muted-foreground">
                  <Truncate>{job.error_summary || job.error}</Truncate>
                </p>
              ) : null}
            </li>
          );
        })}
        </ul>
      </div>
      <JobDetailDialog
        job={detailJob}
        onClose={() => setDetailJob(null)}
        onGoto={
          detailJob && detailPage
            ? () => {
                void leaveNativeView();
                if (detailJob) gotoJobPage(detailJob, kindOf(detailJob.kind));
                setDetailJob(null);
              }
            : undefined
        }
        gotoLabel={detailJob?.status === "failed" && detailJob.kind === "ai_generation" ? t("chatJobsGotoGeneration") : undefined}
      />
    </InspectorCard>
  );
}

function JobStatusIcon({ status }: { status: string }) {
  if (status === "running" || status === "queued") {
    return <Loader2 size={12} className="shrink-0 animate-mosael-spin text-primary" aria-hidden />;
  }
  if (status === "succeeded") {
    return <CheckCircle2 size={12} className="shrink-0 text-success" aria-hidden />;
  }
  if (status === "cancelled") {
    return <Ban size={12} className="shrink-0 text-muted-foreground" aria-hidden />;
  }
  return (
    <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full bg-destructive")} aria-hidden />
  );
}
