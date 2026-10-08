import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Ban, CheckCircle2, CircleAlert, ExternalLink, Loader2, Square } from "lucide-react";
import { toast } from "sonner";

import { cancelJob, getJob, listJobEvents, type Job } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { JobChildrenList, useJobChildren } from "@/components/jobs/JobChildren";
import { JobEventList } from "@/components/jobs/JobEvents";
import { JobResult } from "@/components/jobs/JobResult";
import { EmptyState } from "@/components/layout/EmptyState";
import { useJobKinds } from "@/components/jobs/jobKinds";
import { jobDisplayStatus, runStatusText } from "@/components/jobs/runStatus";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ModalShell } from "@/components/app/modals";
import { Progress } from "@/components/ui/progress";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

const ACTIVE = new Set(["queued", "running", "pending"]);

/** 任务执行详情:该 job 的状态/进度 + task_events 事件时间线(执行记录)。
 *  任务中心点击任意任务打开它——这才是"任务执行记录的某一条详情"。 */
export function JobDetailDialog({
  job,
  onClose,
  onGoto,
  gotoLabel,
}: {
  job: Job | null;
  onClose: () => void;
  onGoto?: () => void;
  gotoLabel?: string;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const { locale } = usePreferences();
  const { kindOf } = useJobKinds();
  // `job` is a snapshot copied out of the list when the row was clicked and never re-synced,
  // so deriving "is it still running" from it left the dialog spinning on a stale progress bar
  // — and polling every 1.5s — for as long as it stayed open. Track the live row instead.
  const live = useQuery({
    queryKey: ["job", job?.id],
    queryFn: () => getJob(job!.id),
    enabled: !!job,
    refetchInterval: (query) => (ACTIVE.has(query.state.data?.status ?? "") ? 1500 : false),
    initialData: job ?? undefined,
  });
  const current = live.data ?? job;
  const active = current ? ACTIVE.has(current.status) : false;

  const events = useQuery({
    queryKey: ["job-events", job?.id],
    queryFn: () => listJobEvents(job!.id),
    enabled: !!job,
    refetchInterval: active ? 1500 : false,
  });

  // 工作流派生的子任务(发布/导出/转写/生成/配音)在这里「收纳」展示——任务中心已不再平铺它们。
  const children = useJobChildren(job?.id ?? null, active);

  /**
   * 中止就放在**看着它跑的这一页**。
   *
   * 此前取消只在任务中心列表那一行上 —— 而点开详情看进度之后,这里没有任何出口:用户看着
   * 一个 38% 的进度条,合理的结论是"启动了就停不下来"。能做的事必须出现在人正看着它的地方。
   */
  const stop = useMutation({
    mutationFn: () => cancelJob(current!.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["job", current?.id] });
      void qc.invalidateQueries({ queryKey: ["job-events", current?.id] });
      void qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (error: Error) => toast.error(errorText(error)),
  });

  return (
    <ModalShell
      open={!!job}
      onOpenChange={(next) => !next && onClose()}
      title={t("jobDetailTitle")}
      footer={
        current ? (
          <>
            {active && (
              <Hint label={t("jobCancelHint")}>
                <Button
                  size="sm"
                  variant="outline"
                  className="mr-auto hover:border-destructive/50 hover:text-destructive"
                  loading={stop.isPending}
                  onClick={() => stop.mutate()}
                >
                  <Square size={13} /> {t("jobCancel")}
                </Button>
              </Hint>
            )}
            {onGoto && <Button size="sm" variant="outline" onClick={onGoto}><ExternalLink size={13} /> {gotoLabel ?? t("jobDetailGoto")}</Button>}
            <Button size="sm" onClick={onClose}>{t("close")}</Button>
          </>
        ) : undefined
      }
    >
      {current && (
        <div className="grid min-w-0 gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full bg-secondary px-[9px] py-px text-ui-xs text-muted-foreground",
                (active || current.status === "running" || current.status === "pending" || current.status === "queued") &&
                  "bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-primary",
                !active && current.status === "succeeded" && "bg-[color-mix(in_srgb,var(--success)_12%,transparent)] text-success",
                !active && jobDisplayStatus(current) === "failed" && "bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] text-destructive",
              )}
            >
              {active ? (
                <Loader2 size={13} className="animate-mosael-spin" />
              ) : current.status === "succeeded" ? (
                <CheckCircle2 size={13} />
              ) : jobDisplayStatus(current) === "cancelled" ? (
                <Ban size={13} />
              ) : (
                <CircleAlert size={13} />
              )}
              {runStatusText(t, active ? "running" : jobDisplayStatus(current))}
            </span>
            <Truncate className="text-ui-xs text-muted-foreground">{kindOf(current.kind).label}</Truncate>
          </div>

          {active && <Progress className="my-0.5" value={Math.round(current.progress * 100)} />}
          <div className="flex min-w-0 items-baseline justify-between gap-2">
            <p className="m-0 min-w-0 text-xs text-foreground [overflow-wrap:anywhere]">{current.message}</p>
            {active && (
              <span className="timecode shrink-0 text-ui-xs tabular-nums text-muted-foreground">
                {Math.round(current.progress * 100)}%
              </span>
            )}
          </div>
          {/* 被停下的任务 error 里只是「已取消」那句,状态那一行已经说了,不再画一行红字。 */}
          {current.error && jobDisplayStatus(current) !== "cancelled" && (
            <p className="m-0 min-w-0 whitespace-pre-wrap text-ui-xs text-destructive [overflow-wrap:anywhere]">
              {current.error}
            </p>
          )}

          {/* 做出了什么:写出来的字、生成的图、写成的笔记 —— 此前这里只有状态和一串 job.* 事件,看不到结果。 */}
          <JobResult job={current} />

          {(children.data ?? []).length > 0 && (
            <div className="grid min-w-0 gap-1 border-t border-border pt-2">
              <span className="text-ui-xs font-semibold text-muted-foreground">{t("jobDetailChildren")}</span>
              <JobChildrenList>{children.data ?? []}</JobChildrenList>
            </div>
          )}

          <div className="grid min-w-0 gap-1 border-t border-border pt-2">
            <span className="text-ui-xs font-semibold text-muted-foreground">{t("jobDetailEvents")}</span>
            {(events.data ?? []).length === 0 && <EmptyState size="compact" icon={<Activity size={15} />} title={t("jobDetailNoEvents")} />}
            <JobEventList events={events.data ?? []} locale={locale} />
          </div>

        </div>
      )}
    </ModalShell>
  );
}
