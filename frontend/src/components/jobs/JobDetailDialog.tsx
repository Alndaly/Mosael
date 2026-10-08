import React from "react";
import { FailureCard, failureFields } from "@/components/failure/FailureCard";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Ban, CheckCircle2, CircleAlert, ExternalLink, Loader2, RotateCcw, Square } from "lucide-react";
import { toast } from "sonner";

import { cancelJob, getJob, listJobEvents, regenerateAssetProxy, type JobSummary } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { JobChildrenList, useJobChildren } from "@/components/jobs/JobChildren";
import { JobEventList } from "@/components/jobs/JobEvents";
import { JobResult } from "@/components/jobs/JobResult";
import { EmptyState } from "@/components/layout/EmptyState";
import { useJobKinds } from "@/components/jobs/jobKinds";
import { runStatusText } from "@/components/jobs/runStatus";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ModalShell } from "@/components/app/modals";
import { Progress } from "@/components/ui/progress";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

const ACTIVE = new Set(["queued", "running"]);

/**
 * 失败了能就地重来的任务种类:怎么重来由那一种自己说(拿载荷里的什么、调哪个接口)。此前失败的任务只有「前往对应页面 / 关闭」,
 * 想重试得自己去找入口(体检 UM-33)。没列在这里的种类不摆「重试」—— 重跑会不会再花钱、要不要换参数,得在它自己的页面里定。
 */
const RETRY: Record<string, (job: JobSummary) => Promise<unknown> | null> = {
  proxy: (job) => (typeof job.payload?.asset_id === "string" ? regenerateAssetProxy(job.payload.asset_id) : null),
};

/** 任务执行详情:该 job 的状态/进度 + task_events 事件时间线(执行记录)。
 *  任务中心点击任意任务打开它——这才是"任务执行记录的某一条详情"。 */
export function JobDetailDialog({
  job,
  onClose,
  onGoto,
  gotoLabel,
}: {
  /** 点开的那一行(列表里的,不带 `result`);详情现取。 */
  job: JobSummary | null;
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
  //: 列表里那一行不带 `result`(做出了什么),所以不拿它当这个查询的初始数据 —— 那样「做出了什么」要等下一次轮询才出来,
  //: 而已经结束的任务不轮询。没取回来之前,状态那几行先用列表里那一行。
  const live = useQuery({
    queryKey: ["job", job?.id],
    queryFn: () => getJob(job!.id),
    enabled: !!job,
    refetchInterval: (query) => (ACTIVE.has(query.state.data?.status ?? "") ? 1500 : false),
  });
  const current: JobSummary | null = live.data ?? job;
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
  const retryable = current && current.status === "failed" ? RETRY[current.kind] : undefined;
  const retry = useMutation({
    mutationFn: () => retryable?.(current!) ?? Promise.resolve(null),
    onSuccess: () => {
      toast.success(t("jobRetryQueued"));
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
            {retryable && (
              <Button size="sm" variant="outline" className={active ? undefined : "mr-auto"} loading={retry.isPending} onClick={() => retry.mutate()}>
                <RotateCcw size={13} /> {t("jobRetry")}
              </Button>
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
                active &&
                  "bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-primary",
                !active && current.status === "succeeded" && "bg-[color-mix(in_srgb,var(--success)_12%,transparent)] text-success",
                !active && current.status === "failed" && "bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] text-destructive",
              )}
            >
              {active ? (
                <Loader2 size={13} className="animate-mosael-spin" />
              ) : current.status === "succeeded" ? (
                <CheckCircle2 size={13} />
              ) : current.status === "cancelled" ? (
                <Ban size={13} />
              ) : (
                <CircleAlert size={13} />
              )}
              {runStatusText(t, active ? "running" : current.status)}
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
          {/* 跑挂了:全应用那一份失败展示 —— 那一句(工作流的照跑挂的那个子任务说)、原因和怎么修、原文在「详情」里 */}
          {current.error && (
            <FailureCard title={t("failureOfKind").replace("{kind}", kindOf(current.kind).label)}
                         {...failureFields(current, current.error)} data-job-failed={current.id} />
          )}

          {/* 做出了什么:写出来的字、生成的图、写成的笔记 —— 此前这里只有状态和一串 job.* 事件,看不到结果。 */}
          {live.data && <JobResult job={live.data} />}

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
