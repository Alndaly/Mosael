import React from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ChevronRight, CircleDashed, Clock, History, Loader2, SkipForward, X, XCircle } from "lucide-react";

import { listJobEvents, listWorkflowRuns, type Job, type TaskEvent } from "@/api/client";
import { useI18n } from "@/app/preferences";

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
  if (status === "succeeded") return <CheckCircle2 size={13} className="wf-hist-ok" />;
  if (status === "failed") return <XCircle size={13} className="wf-hist-err" />;
  if (RUNNING.has(status)) return <Loader2 size={13} className="spin wf-hist-run" />;
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
    <aside className="wf-history" role="dialog" aria-label={t("wfHistory")}>
      <div className="wf-history-head">
        <h2>
          <History size={14} /> {t("wfHistory")}
        </h2>
        <button type="button" className="inspector-delete" aria-label={t("close")} onClick={onClose}>
          <X size={13} />
        </button>
      </div>
      <div className="wf-history-body">
        <div className="wf-history-runs">
          {runs.data && runs.data.length === 0 && <p className="wf-history-empty">{t("wfHistoryEmpty")}</p>}
          {(runs.data ?? []).map((run) => (
            <button
              key={run.id}
              type="button"
              className={run.id === selectedId ? "wf-history-run active" : "wf-history-run"}
              onClick={() => setSelectedId(run.id)}
            >
              <RunIcon status={run.status} />
              <span className="wf-history-run-main">
                <span className="wf-history-run-msg">{run.message || run.status}</span>
                <span className="wf-history-run-meta timecode">
                  {run.created_at ? relTime(run.created_at) : ""}
                  {run.created_at && run.updated_at && ` · ${(ms(run.created_at, run.updated_at) / 1000).toFixed(1)}s`}
                </span>
              </span>
              <ChevronRight size={13} className="wf-history-run-chev" />
            </button>
          ))}
        </div>
        <div className="wf-history-detail">
          {!selected ? (
            <p className="wf-history-empty">{t("wfHistoryPick")}</p>
          ) : (
            <>
              {selected.error && <p className="wf-history-error">{selected.error}</p>}
              <ol className="wf-history-steps">
                {steps.map((s) => (
                  <li key={s.nid} className={`wf-history-step ${s.status}`}>
                    {s.status === "done" ? (
                      <CheckCircle2 size={12} className="wf-hist-ok" />
                    ) : s.status === "skipped" ? (
                      <SkipForward size={12} />
                    ) : (
                      <Loader2 size={12} className="spin wf-hist-run" />
                    )}
                    <span className="wf-history-step-name">{s.name}</span>
                    {s.status === "skipped" ? (
                      <span className="wf-history-step-time timecode">{t("wfStepSkipped")}</span>
                    ) : s.ms != null ? (
                      <span className="wf-history-step-time timecode">
                        <Clock size={10} /> {(s.ms / 1000).toFixed(2)}s
                      </span>
                    ) : null}
                  </li>
                ))}
                {steps.length === 0 && events.isFetched && <p className="wf-history-empty">{t("wfHistoryNoSteps")}</p>}
              </ol>
            </>
          )}
        </div>
      </div>
    </aside>
  );
}
