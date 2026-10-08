/**
 * 一个任务的执行记录(task_events)。
 *
 * **三个消费方**:任务详情弹窗、弹窗里展开的子任务、工作流的运行历史。此前它只长在任务详情
 * 弹窗里,于是子任务只能显示一行「成功 / 生成完成」—— 想知道那一步到底做了什么、失败时原始
 * 返回是什么,只能干瞪眼。把它抽出来之后,"看某个任务的过程"在哪里都是同一副样子。
 *
 * 失败的那条**默认展开**:打开详情就是为了看它,再让人点一下没有道理。
 */

import { FailureCard, failureFields, type FailureSource } from "@/components/failure/FailureCard";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { WorkflowFailureDetails } from "@/components/app/FailureDetails";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";

/**
 * 事件类型 → 给人看的名字。此前执行记录直接显示 `job.queued / job.running / job.failed`,普通用户读不懂(体检 UM-33);
 * 原始类型和完整载荷收进「开发者信息」。认不出的类型照原样显示 —— 编一个名字比显示原名更糟。
 */
const EVENT_LABELS: Record<string, MessageKey> = {
  "job.created": "jobEvent_job_created",
  "job.queued": "jobEvent_job_queued",
  "job.claimed": "jobEvent_job_claimed",
  "job.running": "jobEvent_job_running",
  "job.progress": "jobEvent_job_progress",
  "job.succeeded": "jobEvent_job_succeeded",
  "job.failed": "jobEvent_job_failed",
  "job.cancelled": "jobEvent_job_cancelled",
  "job.remote_cancelled": "jobEvent_job_remote_cancelled",
  "job.resumed": "jobEvent_job_resumed",
  "job.retrieving": "jobEvent_job_retrieving",
  "job.awaiting_worker": "jobEvent_job_awaiting_worker",
  "job.child_killed": "jobEvent_job_child_killed",
  "job.encode_fallback": "jobEvent_job_encode_fallback",
  "workflow.node.started": "jobEvent_workflow_node_started",
  "workflow.node.finished": "jobEvent_workflow_node_finished",
  "workflow.node.failed": "jobEvent_workflow_node_failed",
  "workflow.node.skipped": "jobEvent_workflow_node_skipped",
  "workflow.node.progress": "jobEvent_workflow_node_progress",
  "workflow.finished": "jobEvent_workflow_finished",
  "workflow.failed": "jobEvent_workflow_failed",
  "workflow.cancelled": "jobEvent_workflow_cancelled",
  "publish.status": "jobEvent_publish_status",
  "publish.finished": "jobEvent_publish_finished",
  "publish.failed": "jobEvent_publish_failed",
};

export interface JobEvent {
  id?: string;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

/** 执行记录列表。`compact` 给内嵌场景(子任务展开后)——去掉自己的滚动框,跟着外层滚。 */
export function JobEventList({
  events,
  locale,
  compact = false,
}: {
  events: JobEvent[];
  locale: string;
  compact?: boolean;
}) {
  return (
    <ol
      className={cn(
        "m-0 grid min-w-0 list-none gap-0 p-0",
        !compact && "max-h-[360px] overflow-y-auto overflow-x-hidden",
      )}
    >
      {events.map((event, index) => (
        <EventRow key={event.id ?? `${event.type}-${index}`} event={event} locale={locale} />
      ))}
    </ol>
  );
}

function EventRow({ event, locale }: { event: JobEvent; locale: string }) {
  const t = useI18n();
  const payload = event.payload ?? {};
  const details = asRecord(payload.details);
  const remainder = eventPayloadRemainder(payload);
  const label = EVENT_LABELS[event.type];
  //: 认得出的类型,原名和载荷都收进「开发者信息」,所以总有东西可展开;认不出的照旧。
  const hasDetails = Boolean(details) || Object.keys(remainder).length > 0 || Boolean(label);
  const failed = event.type.endsWith(".failed");
  //: 失败的事件(节点失败、工作流失败):后端在事件上出了那一句、原文、原因和怎么修(按读的人的语言,见 TaskEventOut)
  const failure = failed && (payload.error_summary || payload.error) ? failureFields(payload as FailureSource, String(payload.error ?? "")) : null;

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
            <span className="text-ui-xs text-foreground [overflow-wrap:anywhere]">{label ? t(label) : event.type}</span>
            {eventText(payload) && (
              <small className="min-w-0 text-ui-xs text-muted-foreground [overflow-wrap:anywhere]">
                {eventText(payload)}
              </small>
            )}
          </div>
          <time className="timecode shrink-0 text-ui-2xs text-muted-foreground">
            {relativeTime(event.created_at, locale)}
          </time>
        </summary>
        {hasDetails && (
          <div className="ml-5 mt-2 grid min-w-0 gap-2 pb-1">
            {failure ? <FailureCard size="inline" lines={3} title={t("failureCause")} {...failure} data-event-failed={event.id} /> : null}
            <WorkflowFailureDetails details={details} />
            {/* 原始事件名和完整载荷是排查用的:收起来,要看再展开。 */}
            <details data-event-developer="" className="min-w-0">
              <summary className="cursor-pointer text-ui-2xs font-semibold text-muted-foreground">{t("jobDetailDeveloperInfo")}</summary>
              <div className="mt-1 grid min-w-0 gap-1">
                <code className="text-ui-2xs text-muted-foreground">{event.type}</code>
                {Object.keys(remainder).length > 0 && (
                  <pre className="m-0 max-h-64 min-w-0 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/55 p-2 font-mono text-ui-2xs leading-[1.5] text-foreground" aria-label={t("jobDetailEventPayload")}>
                    {JSON.stringify(remainder, null, 2)}
                  </pre>
                )}
              </div>
            </details>
          </div>
        )}
      </details>
    </li>
  );
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

/** details 已按诊断语义单独呈现;其余载荷保持原结构,避免历史信息被 UI 丢弃。 */
function eventPayloadRemainder(payload: Record<string, unknown>): Record<string, unknown> {
  const remainder = { ...payload };
  delete remainder.details;
  return remainder;
}

function eventText(payload: Record<string, unknown> | null | undefined): string | null {
  if (!payload) return null;
  const p = payload as Record<string, unknown>;
  //: 失败的原因不在这一行里写原文:没有名字的(工作流失败)写后端摘好的那一句,整段在展开的失败展示里
  const candidate = p.name ?? p.message ?? p.error_summary ?? p.error ?? p.status;
  return typeof candidate === "string" ? candidate : null;
}
