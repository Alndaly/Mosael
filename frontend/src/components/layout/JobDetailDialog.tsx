import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, CheckCircle2, CircleAlert, ExternalLink, Loader2 } from "lucide-react";

import { getJob, listJobEvents, type Job } from "@/api/client";
import { JobChildrenList, useJobChildren } from "@/components/layout/JobChildren";
import { JobEventList } from "@/components/layout/JobEvents";
import { EmptyState } from "@/components/layout/EmptyState";
import { useJobKinds } from "@/components/layout/jobKinds";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ModalShell } from "@/components/app/modals";
import { Progress } from "@/components/ui/progress";
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

  return (
    <ModalShell
      open={!!job}
      onOpenChange={(next) => !next && onClose()}
      title={t("jobDetailTitle")}
      footer={
        current ? (
          <>
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
                !active && current.status === "failed" && "bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] text-destructive",
              )}
            >
              {active ? (
                <Loader2 size={13} className="animate-mosael-spin" />
              ) : current.status === "succeeded" ? (
                <CheckCircle2 size={13} />
              ) : (
                <CircleAlert size={13} />
              )}
              {t(`runStatus_${active ? "running" : current.status}` as never)}
            </span>
            <span className="min-w-0 truncate text-ui-xs text-muted-foreground">{kindOf(current.kind).label}</span>
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
          {current.error && (
            <p className="m-0 min-w-0 whitespace-pre-wrap text-ui-xs text-destructive [overflow-wrap:anywhere]">
              {current.error}
            </p>
          )}

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
