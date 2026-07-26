import React from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, Loader2, ExternalLink } from "lucide-react";

import { getJob, listJobChildren, listJobEvents, type Job } from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ModalShell } from "@/components/app/modals";
import { Progress } from "@/components/ui/progress";
import { relativeTime } from "@/lib/time";
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
  const children = useQuery({
    queryKey: ["job-children", job?.id],
    queryFn: () => listJobChildren(job!.id),
    enabled: !!job,
    refetchInterval: active ? 1500 : false,
  });

  return (
    <ModalShell open={!!job} onOpenChange={(next) => !next && onClose()} title={t("jobDetailTitle")}>
      {current && (
        <div className="grid gap-2">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full bg-secondary px-[9px] py-px text-[11px] text-muted-foreground",
                (active || current.status === "running" || current.status === "pending" || current.status === "queued") &&
                  "bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-primary",
                !active && current.status === "succeeded" && "bg-[color-mix(in_srgb,#16a34a_12%,transparent)] text-[#16a34a]",
                !active && current.status === "failed" && "bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] text-destructive",
              )}
            >
              {active ? (
                <Loader2 size={13} className="animate-mibu-spin" />
              ) : current.status === "succeeded" ? (
                <CheckCircle2 size={13} />
              ) : (
                <CircleAlert size={13} />
              )}
              {t(`runStatus_${active ? "running" : current.status}` as never)}
            </span>
            <span className="text-[11px] text-muted-foreground">{t(`jobKind${kindKey(current.kind)}` as never)}</span>
          </div>

          {active && <Progress className="my-0.5" value={Math.round(current.progress * 100)} />}
          <div className="flex items-baseline justify-between gap-2">
            <p className="m-0 text-xs text-foreground">{current.message}</p>
            {active && (
              <span className="timecode shrink-0 text-[11px] tabular-nums text-muted-foreground">
                {Math.round(current.progress * 100)}%
              </span>
            )}
          </div>
          {current.error && <p className="m-0 text-[11.5px] text-destructive">{current.error}</p>}

          {(children.data ?? []).length > 0 && (
            <div className="grid gap-1 border-t border-border pt-2">
              <span className="text-[11px] font-semibold text-muted-foreground">{t("jobDetailChildren")}</span>
              <ul className="m-0 grid list-none gap-0 p-0">
                {(children.data ?? []).map((child) => {
                  const childActive = ACTIVE.has(child.status);
                  const statusKey = childActive
                    ? "running"
                    : child.status === "succeeded" || child.status === "failed"
                      ? child.status
                      : null;
                  return (
                    <li
                      className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-2 py-[5px] [&+&]:border-t [&+&]:border-border"
                      key={child.id}
                    >
                      <div className="grid min-w-0 gap-px">
                        <span className="text-[11.5px] text-foreground">{t(`jobKind${kindKey(child.kind)}` as never)}</span>
                        {child.message && <small className="truncate text-[11px] text-muted-foreground">{child.message}</small>}
                      </div>
                      <span
                        className={cn(
                          "shrink-0 text-[10.5px]",
                          childActive
                            ? "text-primary"
                            : child.status === "succeeded"
                              ? "text-[#16a34a]"
                              : "text-destructive",
                        )}
                      >
                        {statusKey ? t(`runStatus_${statusKey}` as never) : child.status}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          <div className="grid gap-1 border-t border-border pt-2">
            <span className="text-[11px] font-semibold text-muted-foreground">{t("jobDetailEvents")}</span>
            {(events.data ?? []).length === 0 && <p className="m-0 text-[11.5px] text-muted-foreground">{t("jobDetailNoEvents")}</p>}
            <ol className="m-0 grid max-h-60 list-none gap-0 overflow-y-auto p-0">
              {(events.data ?? []).map((event) => (
                <li className="grid grid-cols-[12px_minmax(0,1fr)_auto] items-baseline gap-2 py-[5px] [&+&]:border-t [&+&]:border-border" key={event.id}>
                  <i className="mt-[5px] h-1.5 w-1.5 rounded-full bg-border-strong" />
                  <div className="grid min-w-0 gap-px">
                    <span className="text-[11.5px] text-foreground">{event.type}</span>
                    {eventText(event.payload) && <small className="truncate text-[11px] text-muted-foreground">{eventText(event.payload)}</small>}
                  </div>
                  <time className="timecode text-[10.5px] text-muted-foreground">{relativeTime(event.created_at, locale)}</time>
                </li>
              ))}
            </ol>
          </div>

          <div className="mt-0.5 flex justify-end gap-1.5">
            {onGoto && (
              <Button size="sm" variant="outline" onClick={onGoto}>
                <ExternalLink size={13} /> {gotoLabel ?? t("jobDetailGoto")}
              </Button>
            )}
            <Button size="sm" onClick={onClose}>
              {t("close")}
            </Button>
          </div>
        </div>
      )}
    </ModalShell>
  );
}

function kindKey(kind: string): string {
  const map: Record<string, string> = {
    render: "Render",
    transcribe: "Transcribe",
    ai_generation: "Generation",
    scheduled: "Scheduled",
    workflow: "Workflow",
    publish: "Publish",
    batch: "Batch",
  };
  return map[kind] ?? "Other";
}

function eventText(payload: Record<string, unknown> | null | undefined): string | null {
  if (!payload) return null;
  const p = payload as Record<string, unknown>;
  const candidate = p.name ?? p.message ?? p.error ?? p.status;
  return typeof candidate === "string" ? candidate : null;
}
