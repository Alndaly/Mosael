import React from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, Loader2, ExternalLink } from "lucide-react";

import { listJobEvents, type Job } from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ModalShell } from "@/components/ui/modals";
import { Progress } from "@/components/ui/progress";
import { relativeTime } from "@/lib/time";

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
  const active = job ? ACTIVE.has(job.status) : false;

  const events = useQuery({
    queryKey: ["job-events", job?.id],
    queryFn: () => listJobEvents(job!.id),
    enabled: !!job,
    refetchInterval: active ? 1500 : false,
  });

  return (
    <ModalShell open={!!job} onOpenChange={(next) => !next && onClose()} title={t("jobDetailTitle")}>
      {job && (
        <div className="job-detail">
          <div className="job-detail-head">
            <span className={`job-detail-status s-${active ? "running" : job.status}`}>
              {active ? (
                <Loader2 size={13} className="spin" />
              ) : job.status === "succeeded" ? (
                <CheckCircle2 size={13} />
              ) : (
                <CircleAlert size={13} />
              )}
              {t(`runStatus_${active ? "running" : job.status}` as never)}
            </span>
            <span className="job-detail-kind">{t(`jobKind${kindKey(job.kind)}` as never)}</span>
          </div>

          {active && <Progress className="job-detail-progress" value={Math.round(job.progress * 100)} />}
          <p className="job-detail-msg">{job.message}</p>
          {job.error && <p className="job-detail-error">{job.error}</p>}

          <div className="job-detail-events">
            <span className="job-detail-events-label">{t("jobDetailEvents")}</span>
            {(events.data ?? []).length === 0 && <p className="job-detail-empty">{t("jobDetailNoEvents")}</p>}
            <ol className="job-events">
              {(events.data ?? []).map((event) => (
                <li className="job-event" key={event.id}>
                  <i className="job-event-dot" />
                  <div className="job-event-body">
                    <span className="job-event-type">{event.type}</span>
                    {eventText(event.payload) && <small className="job-event-text">{eventText(event.payload)}</small>}
                  </div>
                  <time className="job-event-time timecode">{relativeTime(event.created_at, locale)}</time>
                </li>
              ))}
            </ol>
          </div>

          <div className="job-detail-actions">
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
