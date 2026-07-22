import React from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ChevronRight, CircleDashed, Clock, History, Loader2, SkipForward, X, XCircle } from "lucide-react";

import { listJobEvents, listWorkflowRuns, type Job, type TaskEvent } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

const RUNNING = new Set(["queued", "running"]);

function relTime(iso: string): string {
  const d = Date.parse(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  const s = Math.max(0, (Date.now() - d) / 1000);
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}
function ms(a: string, b: string): number {
  const p = (i: string) => Date.parse(i.endsWith("Z") || i.includes("+") ? i : i + "Z");
  return Math.max(0, p(b) - p(a));
}

type Step = { nid: string; name: string; status: "running" | "done" | "skipped"; ms?: number };

/** Reduce a run's task events into an ordered per-node step list (Dify-style detail). */
function toSteps(events: TaskEvent[]): Step[] {
  const order: string[] = [];
  const byNode = new Map<string, Step>();
  const sorted = [...events].sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""));
  for (const e of sorted) {
    const p = (e.payload ?? {}) as { node_id?: string; name?: string };
    const nid = p.node_id ?? "";
    if (!nid) continue;
    if (e.type === "workflow.node.started") {
      if (!byNode.has(nid)) order.push(nid);
      byNode.set(nid, { nid, name: p.name ?? nid, status: "running" });
      (byNode.get(nid) as Step & { _start?: string })._start = e.created_at;
    } else if (e.type === "workflow.node.finished") {
      const s = byNode.get(nid) as (Step & { _start?: string }) | undefined;
      if (s) {
        s.status = "done";
        if (s._start && e.created_at) s.ms = ms(s._start, e.created_at);
      }
    } else if (e.type === "workflow.node.skipped") {
      if (!byNode.has(nid)) order.push(nid);
      byNode.set(nid, { nid, name: p.name ?? nid, status: "skipped" });
    }
  }
  return order.map((nid) => byNode.get(nid)!).filter(Boolean);
}

function RunIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 size={13} className="text-[#3fb950]" />;
  if (status === "failed") return <XCircle size={13} className="text-[#e5484d]" />;
  if (RUNNING.has(status)) return <Loader2 size={13} className="spin text-primary" />;
  return <CircleDashed size={13} />;
}

export function WorkflowRunHistory({ workflowId, onClose }: { workflowId: string; onClose: () => void }) {
  const t = useI18n();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

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
          {runs.data && runs.data.length === 0 && <p className="px-2 py-3 text-center text-[11.5px] text-muted-foreground">{t("wfHistoryEmpty")}</p>}
          {(runs.data ?? []).map((run) => (
            <button
              key={run.id}
              type="button"
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-foreground hover:bg-[rgb(255_255_255/0.05)]",
                run.id === selectedId && "bg-[rgb(255_255_255/0.08)] hover:bg-[rgb(255_255_255/0.08)]",
              )}
              onClick={() => setSelectedId(run.id)}
            >
              <RunIcon status={run.status} />
              <span className="flex min-w-0 flex-1 flex-col gap-px">
                <span className="truncate text-xs">{run.message || run.status}</span>
                <span className="timecode text-[10.5px] text-muted-foreground">
                  {run.created_at ? relTime(run.created_at) : ""}
                  {run.created_at && run.updated_at && ` · ${(ms(run.created_at, run.updated_at) / 1000).toFixed(1)}s`}
                </span>
              </span>
              <ChevronRight size={13} className="shrink-0 text-muted-foreground" />
            </button>
          ))}
        </div>
        <div className="overflow-y-auto px-2.5 py-2">
          {!selected ? (
            <p className="px-2 py-3 text-center text-[11.5px] text-muted-foreground">{t("wfHistoryPick")}</p>
          ) : (
            <>
              {selected.error && <p className="mb-2 mt-0 whitespace-pre-wrap text-[11.5px] text-destructive">{selected.error}</p>}
              <ol className="m-0 flex list-none flex-col gap-0.5 p-0">
                {steps.map((s) => (
                  <li key={s.nid} className={cn("flex items-center gap-[7px] rounded-md px-1.5 py-1 text-xs", s.status === "skipped" && "opacity-55")}>
                    {s.status === "done" ? (
                      <CheckCircle2 size={12} className="text-[#3fb950]" />
                    ) : s.status === "skipped" ? (
                      <SkipForward size={12} />
                    ) : (
                      <Loader2 size={12} className="spin text-primary" />
                    )}
                    <span className="min-w-0 flex-1 truncate">{s.name}</span>
                    {s.status === "skipped" ? (
                      <span className="timecode inline-flex items-center gap-[3px] text-[10.5px] text-muted-foreground">{t("wfStepSkipped")}</span>
                    ) : s.ms != null ? (
                      <span className="timecode inline-flex items-center gap-[3px] text-[10.5px] text-muted-foreground">
                        <Clock size={10} /> {(s.ms / 1000).toFixed(2)}s
                      </span>
                    ) : null}
                  </li>
                ))}
                {steps.length === 0 && events.isFetched && <p className="px-2 py-3 text-center text-[11.5px] text-muted-foreground">{t("wfHistoryNoSteps")}</p>}
              </ol>
            </>
          )}
        </div>
      </div>
    </aside>
  );
}
