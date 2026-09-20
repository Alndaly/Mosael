/**
 * 一个任务的执行记录(task_events)。
 *
 * **三个消费方**:任务详情弹窗、弹窗里展开的子任务、工作流的运行历史。此前它只长在任务详情
 * 弹窗里,于是子任务只能显示一行「成功 / 生成完成」—— 想知道那一步到底做了什么、失败时原始
 * 返回是什么,只能干瞪眼。把它抽出来之后,"看某个任务的过程"在哪里都是同一副样子。
 *
 * 失败的那条**默认展开**:打开详情就是为了看它,再让人点一下没有道理。
 */

import { useI18n } from "@/app/preferences";
import { WorkflowFailureDetails } from "@/components/app/FailureDetails";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";

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

/** details 已按诊断语义单独呈现;其余载荷保持原结构,避免历史信息被 UI 丢弃。 */
function eventPayloadRemainder(payload: Record<string, unknown>): Record<string, unknown> {
  const remainder = { ...payload };
  delete remainder.details;
  return remainder;
}

function eventText(payload: Record<string, unknown> | null | undefined): string | null {
  if (!payload) return null;
  const p = payload as Record<string, unknown>;
  const candidate = p.name ?? p.message ?? p.error ?? p.status;
  return typeof candidate === "string" ? candidate : null;
}
