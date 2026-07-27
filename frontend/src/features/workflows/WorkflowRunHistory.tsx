import React from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, ChevronRight, CircleDashed, Clock, History, Loader2, SkipForward, X, XCircle } from "lucide-react";

import { listJobEvents, listWorkflowRuns, type Job, type TaskEvent } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

const RUNNING = new Set(["queued", "running"]);

function parseIso(iso: string): number {
  return Date.parse(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
}
function relTime(iso: string, now: number): string {
  const s = Math.max(0, (now - parseIso(iso)) / 1000);
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}
function ms(a: string, b: string): number {
  return Math.max(0, parseIso(b) - parseIso(a));
}

type Step = {
  nid: string;
  name: string;
  status: "running" | "done" | "skipped" | "failed";
  ms?: number;
  startAt?: number;
  outputs?: Record<string, unknown>;
  error?: string;
};

/** Reduce a run's task events into an ordered per-node step list (Dify-style detail). */
function toSteps(events: TaskEvent[]): Step[] {
  const order: string[] = [];
  const byNode = new Map<string, Step>();
  const sorted = [...events].sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""));
  for (const e of sorted) {
    const p = (e.payload ?? {}) as { node_id?: string; name?: string; outputs?: Record<string, unknown>; error?: string };
    const nid = p.node_id ?? "";
    if (!nid) continue;
    if (e.type === "workflow.node.started") {
      if (!byNode.has(nid)) order.push(nid);
      byNode.set(nid, { nid, name: p.name ?? nid, status: "running", startAt: e.created_at ? parseIso(e.created_at) : undefined });
    } else if (e.type === "workflow.node.finished") {
      const s = byNode.get(nid);
      if (s) {
        s.status = "done";
        s.outputs = p.outputs;
        if (s.startAt != null && e.created_at) s.ms = Math.max(0, parseIso(e.created_at) - s.startAt);
      }
    } else if (e.type === "workflow.node.failed") {
      const s = byNode.get(nid);
      if (s) {
        s.status = "failed";
        s.error = p.error;
        if (s.startAt != null && e.created_at) s.ms = Math.max(0, parseIso(e.created_at) - s.startAt);
      }
    } else if (e.type === "workflow.node.skipped") {
      if (!byNode.has(nid)) order.push(nid);
      byNode.set(nid, { nid, name: p.name ?? nid, status: "skipped" });
    }
  }
  return order.map((nid) => byNode.get(nid)!).filter(Boolean);
}

/** 输出摘要拼成可读文本:字符串原样(引擎侧已截断),其余 JSON 化。 */
function outputsText(outputs: Record<string, unknown>): string {
  return Object.entries(outputs)
    .map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join("\n");
}

function RunIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 size={13} className="text-[#3fb950]" />;
  if (status === "failed") return <XCircle size={13} className="text-[#e5484d]" />;
  if (RUNNING.has(status)) return <Loader2 size={13} className="animate-openstudio-spin text-primary" />;
  return <CircleDashed size={13} />;
}

export function WorkflowRunHistory({ workflowId, onClose }: { workflowId: string; onClose: () => void }) {
  const t = useI18n();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [expanded, setExpanded] = React.useState<Set<string>>(() => new Set());

  const runs = useQuery({
    queryKey: ["workflow-runs", workflowId],
    queryFn: () => listWorkflowRuns(workflowId),
    refetchInterval: (q) => ((q.state.data as Job[] | undefined)?.some((j) => RUNNING.has(j.status)) ? 2000 : false),
  });
  React.useEffect(() => {
    if (!selectedId && runs.data && runs.data.length > 0) setSelectedId(runs.data[0].id);
  }, [runs.data, selectedId]);

  const selected = runs.data?.find((j) => j.id === selectedId) ?? null;
  const events = useQuery({
    queryKey: ["job-events", selectedId],
    queryFn: () => listJobEvents(selectedId!),
    enabled: !!selectedId,
    refetchInterval: selected && RUNNING.has(selected.status) ? 1500 : false,
  });
  const steps = React.useMemo(() => toSteps(events.data ?? []), [events.data]);

  // 数据 2s 一轮询,但耗时显示要每秒走字:运行中的 run/节点用 now 与开始时间实时求差,
  // 而不是等下一次轮询把 updated_at 带回来。没有任何东西在跑时不启动定时器。
  const anyRunning = (runs.data ?? []).some((j) => RUNNING.has(j.status));
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    if (!anyRunning) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [anyRunning]);

  const toggleExpanded = (nid: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(nid)) next.delete(nid);
      else next.add(nid);
      return next;
    });

  return (
    <aside className="absolute bottom-2 right-2 top-2 z-40 flex w-[340px] flex-col overflow-hidden rounded-lg border border-border bg-[rgb(12_12_14/0.94)] backdrop-blur-[10px]" role="dialog" aria-label={t("wfHistory")}>
      <div className="flex h-[34px] items-center border-b border-border pl-2.5 pr-1.5 [&_h2]:flex [&_h2]:flex-1 [&_h2]:items-center [&_h2]:gap-1.5 [&_h2]:text-[12.5px] [&_h2]:font-semibold">
        <h2>
          <History size={14} /> {t("wfHistory")}
        </h2>
        <button type="button" className="grid h-6 w-6 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[color,background] duration-100 hover:bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)] hover:text-destructive" aria-label={t("close")} onClick={onClose}>
          <X size={13} />
        </button>
      </div>
      <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="overflow-y-auto border-b border-border p-1">
          {runs.data && runs.data.length === 0 && (
            <div className="grid h-full place-items-center">
              <p className="m-0 px-2 text-center text-[11.5px] text-muted-foreground">{t("wfHistoryEmpty")}</p>
            </div>
          )}
          {(runs.data ?? []).map((run) => (
            <button
              key={run.id}
              type="button"
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-foreground hover:bg-secondary",
                run.id === selectedId && "bg-accent hover:bg-accent",
              )}
              onClick={() => setSelectedId(run.id)}
            >
              <RunIcon status={run.status} />
              <span className="flex min-w-0 flex-1 flex-col gap-px">
                <span className="truncate text-xs">{run.message || run.status}</span>
                <span className="timecode text-[10.5px] text-muted-foreground">
                  {run.created_at ? relTime(run.created_at, now) : ""}
                  {run.created_at && RUNNING.has(run.status)
                    ? ` · ${Math.max(0, (now - parseIso(run.created_at)) / 1000).toFixed(0)}s`
                    : run.created_at && run.updated_at && ` · ${(ms(run.created_at, run.updated_at) / 1000).toFixed(1)}s`}
                </span>
              </span>
              <ChevronRight size={13} className="shrink-0 text-muted-foreground" />
            </button>
          ))}
        </div>
        <div className="overflow-y-auto px-2.5 py-2">
          {!selected ? (
            <div className="grid h-full place-items-center">
              <p className="m-0 px-2 text-center text-[11.5px] text-muted-foreground">{t("wfHistoryPick")}</p>
            </div>
          ) : (
            <>
              {selected.error && <p className="mb-2 mt-0 whitespace-pre-wrap text-[11.5px] text-destructive">{selected.error}</p>}
              <ol className="m-0 flex list-none flex-col gap-0.5 p-0">
                {steps.map((s) => {
                  const hasDetail = (s.outputs && Object.keys(s.outputs).length > 0) || Boolean(s.error);
                  const open = expanded.has(s.nid);
                  return (
                    <li key={s.nid} className={cn("rounded-md text-xs", s.status === "skipped" && "opacity-55")}>
                      <button
                        type="button"
                        className={cn(
                          "flex w-full items-center gap-[7px] rounded-md border-0 bg-transparent px-1.5 py-1 text-left text-xs text-foreground",
                          hasDetail && "cursor-pointer hover:bg-secondary",
                        )}
                        onClick={() => hasDetail && toggleExpanded(s.nid)}
                        aria-expanded={hasDetail ? open : undefined}
                      >
                        {s.status === "done" ? (
                          <CheckCircle2 size={12} className="shrink-0 text-[#3fb950]" />
                        ) : s.status === "failed" ? (
                          <XCircle size={12} className="shrink-0 text-[#e5484d]" />
                        ) : s.status === "skipped" ? (
                          <SkipForward size={12} className="shrink-0" />
                        ) : (
                          <Loader2 size={12} className="animate-openstudio-spin shrink-0 text-primary" />
                        )}
                        <span className="min-w-0 flex-1 truncate">{s.name}</span>
                        {s.status === "skipped" ? (
                          <span className="timecode inline-flex items-center gap-[3px] text-[10.5px] text-muted-foreground">{t("wfStepSkipped")}</span>
                        ) : s.status === "running" && s.startAt != null ? (
                          <span className="timecode inline-flex items-center gap-[3px] text-[10.5px] text-muted-foreground">
                            <Clock size={10} /> {Math.max(0, (now - s.startAt) / 1000).toFixed(0)}s
                          </span>
                        ) : s.ms != null ? (
                          <span className="timecode inline-flex items-center gap-[3px] text-[10.5px] text-muted-foreground">
                            <Clock size={10} /> {(s.ms / 1000).toFixed(2)}s
                          </span>
                        ) : null}
                        {hasDetail && (
                          <ChevronDown size={11} className={cn("shrink-0 text-muted-foreground transition-transform duration-100", !open && "-rotate-90")} />
                        )}
                      </button>
                      {open && s.error && (
                        <p className="mx-1.5 mb-1 mt-0.5 whitespace-pre-wrap break-words rounded-md bg-[color-mix(in_oklab,var(--destructive)_12%,transparent)] px-2 py-1.5 text-[10.5px] leading-[1.5] text-destructive">
                          {s.error}
                        </p>
                      )}
                      {open && s.outputs && Object.keys(s.outputs).length > 0 && (
                        <pre className="mx-1.5 mb-1 mt-0.5 max-h-44 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-muted px-2 py-1.5 font-mono text-[10.5px] leading-[1.55] text-muted-foreground">
                          {outputsText(s.outputs)}
                        </pre>
                      )}
                    </li>
                  );
                })}
                {steps.length === 0 && events.isFetched && <p className="px-2 py-3 text-center text-[11.5px] text-muted-foreground">{t("wfHistoryNoSteps")}</p>}
              </ol>
            </>
          )}
        </div>
      </div>
    </aside>
  );
}
