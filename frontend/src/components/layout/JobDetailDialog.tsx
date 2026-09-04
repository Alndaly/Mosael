import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, CheckCircle2, CircleAlert, ExternalLink, Loader2 } from "lucide-react";

import { getJob, listJobChildren, listJobEvents, type Job } from "@/api/client";
import { EmptyState } from "@/components/layout/EmptyState";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ModalShell } from "@/components/app/modals";
import { Progress } from "@/components/ui/progress";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { WorkflowFailureDetails } from "@/features/workflows/WorkflowFailureDetails";

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
                !active && current.status === "succeeded" && "bg-[color-mix(in_srgb,#16a34a_12%,transparent)] text-[#16a34a]",
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
            <span className="min-w-0 truncate text-ui-xs text-muted-foreground">{t(`jobKind${kindKey(current.kind)}` as never)}</span>
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
                        <span className="text-ui-xs text-foreground">{t(`jobKind${kindKey(child.kind)}` as never)}</span>
                        {child.message && <small className="truncate text-ui-xs text-muted-foreground">{child.message}</small>}
                      </div>
                      <span
                        className={cn(
                          "shrink-0 text-ui-2xs",
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

          <div className="grid min-w-0 gap-1 border-t border-border pt-2">
            <span className="text-ui-xs font-semibold text-muted-foreground">{t("jobDetailEvents")}</span>
            {(events.data ?? []).length === 0 && <EmptyState size="compact" icon={<Activity size={15} />} title={t("jobDetailNoEvents")} />}
            <ol className="m-0 grid min-w-0 max-h-[360px] list-none gap-0 overflow-x-hidden overflow-y-auto p-0">
              {(events.data ?? []).map((event) => (
                <EventRow key={event.id} event={event} locale={locale} />
              ))}
            </ol>
          </div>

        </div>
      )}
    </ModalShell>
  );
}

function EventRow({
  event,
  locale,
}: {
  event: { type: string; payload: Record<string, unknown>; created_at: string };
  locale: string;
}) {
  const t = useI18n();
  const payload = event.payload ?? {};
  const details = asRecord(payload.details);
  const remainder = eventPayloadRemainder(payload);
  const hasDetails = Boolean(details) || Object.keys(remainder).length > 0;
  const failed = event.type.endsWith(".failed");

  return (
    <li className="min-w-0 py-[5px] [&+&]:border-t [&+&]:border-border">
      <details className="group min-w-0" open={failed && hasDetails}>
        <summary
          className={cn(
            "grid min-w-0 list-none grid-cols-[12px_minmax(0,1fr)_auto] items-baseline gap-2 marker:content-none",
            hasDetails && "cursor-pointer",
          )}
        >
          <i className={cn("mt-[5px] h-1.5 w-1.5 rounded-full bg-border-strong", failed && "bg-destructive")} />
          <div className="grid min-w-0 gap-px">
            <span className="text-ui-xs text-foreground [overflow-wrap:anywhere]">{event.type}</span>
            {eventText(payload) && (
              <small className="min-w-0 text-ui-xs text-muted-foreground [overflow-wrap:anywhere]">{eventText(payload)}</small>
            )}
          </div>
          <time className="timecode shrink-0 text-ui-2xs text-muted-foreground">{relativeTime(event.created_at, locale)}</time>
        </summary>
        {hasDetails && (
          <div className="ml-5 mt-2 grid min-w-0 gap-2 pb-1">
            <WorkflowFailureDetails details={details} />
            {Object.keys(remainder).length > 0 && (
              <div className="grid min-w-0 gap-1">
                <span className="text-ui-2xs font-semibold text-muted-foreground">{t("jobDetailEventPayload")}</span>
                <pre className="m-0 max-h-64 min-w-0 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/55 p-2 font-mono text-ui-2xs leading-[1.5] text-foreground">
                  {JSON.stringify(remainder, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </details>
    </li>
  );
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

/** details 已按诊断语义单独呈现；其余载荷保持原结构，避免历史信息被 UI 丢弃。 */
function eventPayloadRemainder(payload: Record<string, unknown>): Record<string, unknown> {
  const remainder = { ...payload };
  delete remainder.details;
  return remainder;
}

function kindKey(kind: string): string {
  const map: Record<string, string> = {
    render: "Render",
    transcribe: "Transcribe",
    ai_generation: "Generation",
    scheduled: "Scheduled",
    workflow: "Workflow",
    publish: "Publish",
  };
  return map[kind] ?? "Other";
}

function eventText(payload: Record<string, unknown> | null | undefined): string | null {
  if (!payload) return null;
  const p = payload as Record<string, unknown>;
  const candidate = p.name ?? p.message ?? p.error ?? p.status;
  return typeof candidate === "string" ? candidate : null;
}
