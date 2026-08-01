import React from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, ChevronRight, CircleDashed, Clock, History, Loader2, Move, PanelRight, SkipForward, X, XCircle } from "lucide-react";

import { api, listJobEvents, listWorkflowRuns, type Asset, type Job, type TaskEvent } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { AssetInlinePreview } from "@/components/app/asset-preview";
import { assetOutputs, parseIso, toSteps, type Step } from "@/features/workflows/runSteps";
import { PANEL_HEADER_CLASS, useFloatingPanel } from "@/features/workflows/useFloatingPanel";
import type { WorkflowAgentMode } from "@/features/workflows/WorkflowAgentChat";
import { cn } from "@/lib/utils";

const RUNNING = new Set(["queued", "running"]);

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



/** 素材产出的预览条。素材可能已被删除(取不到就不渲染),所以查询失败是正常路径不是错误。 */
function StepAssets({ assetIds }: { assetIds: string[] }) {
  const assets = useQueries({
    queries: assetIds.map((id) => ({
      queryKey: ["asset", id],
      queryFn: () => api<Asset>(`/api/assets/${id}`),
      staleTime: 60_000,
      retry: false,
    })),
  });
  const ready = assets.map((q) => q.data).filter(Boolean) as Asset[];
  if (ready.length === 0) return null;
  return (
    <div className="mx-1.5 mb-1 mt-0.5 flex flex-wrap gap-1.5">
      {ready.map((asset) => (
        <AssetInlinePreview
          key={asset.id}
          assetId={asset.id}
          name={asset.name || asset.original_filename}
          kind={asset.kind}
          // 历史面板是窄列,压到缩略图刻度。
          className={
            asset.kind === "image"
              ? "block max-h-[120px] w-auto max-w-full object-contain"
              : asset.kind === "video"
                ? "max-h-[140px] max-w-full rounded-md border border-border bg-black"
                : "w-full max-w-[240px]"
          }
        />
      ))}
    </div>
  );
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

export function WorkflowRunHistory({
  workflowId,
  nodeTypeById = {},
  mode,
  onModeChange,
  onClose,
}: {
  workflowId: string;
  /** 节点 id → 类型。用来查这一步的输出里哪些是素材(见 OUTPUT_TYPES)。
   *  历史里的节点可能已被删改,查不到就退回纯文本 —— 不猜。 */
  nodeTypeById?: Record<string, string>;
  /** 与 AI 助手同一套:停靠在右栏,或浮成可拖动、可八向缩放的小窗。 */
  mode: WorkflowAgentMode;
  onModeChange: (mode: WorkflowAgentMode) => void;
  onClose: () => void;
}) {
  const isFloating = mode === "floating";
  const { style: floatStyle, startDrag, handles, focusProps } = useFloatingPanel({
    storageKey: "openstudio.wf.history.rect.v1",
    floating: isFloating,
    // 历史是列表,窄一点就够;高度给足,一屏能看到步骤和产物。
    preferredW: 400,
    preferredH: 620,
    minW: 300,
  });
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
  // 运行**结束后**必须再拉一次。轮询是「run 还在跑才开」,而 run 的状态先翻成终态、最后那批
  // node.finished 事件随后才落库 —— 只靠轮询会停在结束前的那张快照上,最后一个节点(通常是最慢的
  // 那个)于是永远显示在转圈。用 run 的终态 + updated_at 当依赖,翻终态时补一次。
  const settledKey = selected && !RUNNING.has(selected.status) ? `${selected.id}:${selected.updated_at}` : null;
  React.useEffect(() => {
    if (settledKey) void events.refetch();
    // events.refetch 引用稳定由 react-query 保证
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settledKey]);
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

  // 和 AI 助手一样停靠在右栏,不再是盖在画布上的悬浮层:悬浮会挡住正在跑的节点,
  // 而运行时恰恰要同时看见画布和这里。
  return (
    <aside
      className={cn(
        "flex flex-col overflow-hidden rounded-lg border border-border bg-panel",
        isFloating
          ? "fixed max-h-[calc(100vh-24px)] max-w-[calc(100vw-24px)] border-border-strong"
          : "relative min-h-0 min-w-0",
      )}
      style={floatStyle}
      {...focusProps}
      role={isFloating ? "dialog" : "complementary"}
      aria-label={t("wfHistory")}
    >
      {handles}
      <div
        className={cn(
          PANEL_HEADER_CLASS,
          isFloating && "cursor-move",
        )}
        onPointerDown={startDrag}
      >
        <h2>
          <History size={14} /> {t("wfHistory")}
        </h2>
        <button
          type="button"
          className="grid h-6 w-6 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[color,background] duration-100 hover:bg-secondary hover:text-foreground"
          aria-label={isFloating ? t("wfAgentDock") : t("wfAgentFloat")}
          title={isFloating ? t("wfAgentDock") : t("wfAgentFloat")}
          onClick={() => onModeChange(isFloating ? "docked" : "floating")}
        >
          {isFloating ? <PanelRight size={13} /> : <Move size={13} />}
        </button>
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
                      {open && s.outputs && assetOutputs(nodeTypeById[s.nid] ?? "", s.outputs).length > 0 && (
                        <StepAssets assetIds={assetOutputs(nodeTypeById[s.nid] ?? "", s.outputs)} />
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
