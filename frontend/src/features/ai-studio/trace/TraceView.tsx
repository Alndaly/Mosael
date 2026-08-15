/**
 * 轨迹视图:同一段对话的另一种读法 —— 不看它说了什么,看它做了什么、时间花在哪儿。
 *
 * 对话视图是给「读答案」的人用的:一段段正文,工具调用折在卡片里。轨迹是给**排查**的人用的:
 * 一步一行、可搜、可点开看原始参数与返回,上面一条概览条把整个会话压成三行色块。同一份数据,
 * 谁都不必迁就谁。
 *
 * 全部数字都可能是「不知道」:老会话没有首 token 打点,供应商可能不报缓存 token,正在跑的工具
 * 还没有时长。这里一律显示 `—`,不显示 0 —— 一个假的精确值比一个空位难发现得多。
 */
import React from "react";
import { ChevronRight, Clock, ListOrdered, SearchX, X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/layout/EmptyState";
import type { AgentTimelineItem } from "@/components/agent/ToolCalls";
import type { AgentUsageEvent } from "@/features/ai-studio/messageUsage";
import { formatElapsedSeconds } from "@/lib/time";
import { cn } from "@/lib/utils";
import { buildTurns, traceStats, type TraceEvent, type TraceTurn } from "./traceModel";
import { deriveTraceTimeline, type TraceTimelineMode } from "./traceTimeline";

type TraceMessage = {
  id: string;
  role: string;
  content: string;
  error?: string | null;
  created_at: string;
  payload: unknown;
};

/** 未知一律「—」。整个视图只有这一处决定「没有的数长什么样」。 */
function orDash(value: string | null | undefined): string {
  return value == null || value === "" ? "—" : value;
}

function seconds(value: number | null): string {
  return value == null ? "—" : formatElapsedSeconds(value);
}

function tokens(value: number | null): string {
  if (value == null) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)}K`;
  return String(value);
}

const KIND_LABEL: Record<TraceEvent["kind"], string> = {
  user: "traceKindUser",
  text: "traceKindAssistant",
  thinking: "traceKindThinking",
  tool: "traceKindTool",
  compaction: "traceKindCompaction",
  error: "traceKindError",
};

/** 行首那枚标签的配色。工具用主色、错误用危险色,其余中性 —— 扫一眼就能定位到工具那几行。 */
const KIND_TONE: Record<TraceEvent["kind"], string> = {
  user: "border-border text-muted-foreground",
  text: "border-border text-foreground",
  thinking: "border-dashed border-border text-muted-foreground",
  tool: "border-[color-mix(in_srgb,var(--primary)_40%,var(--border))] text-primary",
  compaction: "border-dashed border-border text-muted-foreground",
  error: "border-[color-mix(in_srgb,var(--destructive)_45%,var(--border))] text-destructive",
};

const LANE_TONE = [
  "bg-[color-mix(in_srgb,var(--muted-foreground)_45%,transparent)]",
  "bg-[color-mix(in_srgb,var(--primary)_65%,transparent)]",
  "bg-[color-mix(in_srgb,var(--warning,var(--primary))_70%,transparent)]",
];

/** 概览条:三行色块 + 轮边界。点一块跳到对应那一步。 */
function TraceOverview({
  turns,
  mode,
  selectedKey,
  onSelect,
}: {
  turns: TraceTurn[];
  mode: TraceTimelineMode;
  selectedKey: string | null;
  onSelect: (key: string) => void;
}) {
  const t = useI18n();
  const model = React.useMemo(() => deriveTraceTimeline(turns, mode), [turns, mode]);
  if (!model) {
    // 时长投影下可能一条带时间戳的记录都没有(全是老数据)—— 说清楚是没得画,而不是画了个空的。
    return (
      <div className="border-b border-border px-3 py-2 text-ui-2xs text-muted-foreground">
        {t("traceNoTiming")}
      </div>
    );
  }
  const span = Math.max(1e-6, model.end - model.start);
  const pct = (value: number) => ((value - model.start) / span) * 100;
  const laneNames = [t("traceLaneInput"), t("traceLaneModel"), t("traceLaneTools")];

  return (
    <div className="grid gap-1 border-b border-border px-3 py-2">
      {[0, 1, 2].map((lane) => (
        <div key={lane} className="grid grid-cols-[52px_minmax(0,1fr)] items-center gap-2">
          <span className="truncate text-ui-2xs uppercase tracking-[0.06em] text-muted-foreground">{laneNames[lane]}</span>
          <div className="relative h-2.5 rounded-sm bg-[color-mix(in_srgb,var(--foreground)_5%,transparent)]">
            {model.spans
              .filter((item) => item.lane === lane)
              .map((item) => (
                <button
                  key={item.key}
                  type="button"
                  title={`${t(KIND_LABEL[item.kind === "turn" ? "text" : item.kind] as never)}${item.label ? ` · ${item.label}` : ""}`}
                  aria-label={item.label || t(KIND_LABEL[item.kind === "turn" ? "text" : item.kind] as never)}
                  onClick={() => item.eventKey && onSelect(item.eventKey)}
                  className={cn(
                    "absolute inset-y-0 min-w-[2px] cursor-pointer rounded-[2px] border-0 p-0",
                    item.kind === "turn"
                      ? "bg-[color-mix(in_srgb,var(--primary)_18%,transparent)]"
                      : LANE_TONE[lane],
                    item.isError && "bg-[color-mix(in_srgb,var(--destructive)_70%,transparent)]",
                    item.eventKey && item.eventKey === selectedKey && "outline outline-2 outline-offset-1 outline-ring",
                  )}
                  style={{ left: `${pct(item.start)}%`, width: `${Math.max(0.4, pct(item.end) - pct(item.start))}%` }}
                />
              ))}
          </div>
        </div>
      ))}
      {/* 压缩量必须说出来:一条被挤掉两小时空闲的轴,不标注就是在骗人说「一直在跑」。 */}
      {model.compressedIdleMs > 1000 && (
        <p className="m-0 pl-[60px] text-ui-2xs text-muted-foreground">
          {t("traceIdleCompressed").replace("{t}", formatElapsedSeconds(model.compressedIdleMs / 1000))}
        </p>
      )}
    </div>
  );
}

/** 底部统计条。缺的项直接不出现,而不是占个位显示 0。 */
function TraceStatsBar({ turns, usageEvents }: { turns: TraceTurn[]; usageEvents: AgentUsageEvent[] }) {
  const t = useI18n();
  const stats = React.useMemo(() => traceStats(turns, usageEvents), [turns, usageEvents]);
  const parts: string[] = [
    `${t("traceStatTurns").replace("{n}", String(stats.turns))} · ${t("traceStatSteps").replace("{n}", String(stats.steps))}`,
  ];
  if (stats.llmSeconds != null || stats.toolSeconds != null) {
    parts.push(
      `${t("traceStatModel").replace("{t}", seconds(stats.llmSeconds))} · ${t("traceStatTools").replace("{t}", seconds(stats.toolSeconds))}`,
    );
  }
  if (stats.firstTokenSeconds != null) {
    parts.push(t("traceStatFirstToken").replace("{t}", seconds(stats.firstTokenSeconds)));
  }
  if (stats.outputTokensPerSecond != null) {
    parts.push(t("traceStatThroughput").replace("{n}", stats.outputTokensPerSecond.toFixed(0)));
  }
  if (stats.cacheHitRate != null) {
    parts.push(t("traceStatCache").replace("{n}", (stats.cacheHitRate * 100).toFixed(0)));
  }
  if (stats.inputTokens != null || stats.outputTokens != null) {
    parts.push(
      `${t("traceStatInput").replace("{n}", tokens(stats.inputTokens))} · ${t("traceStatOutput").replace("{n}", tokens(stats.outputTokens))}`,
    );
  }
  if (stats.failedToolCalls > 0) {
    parts.push(t("traceStatFailed").replace("{n}", String(stats.failedToolCalls)));
  }

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 border-t border-border px-3 py-1.5 text-ui-2xs text-muted-foreground">
      {parts.map((part, index) => (
        <React.Fragment key={part}>
          {index > 0 && <span aria-hidden className="opacity-40">|</span>}
          <span>{part}</span>
        </React.Fragment>
      ))}
      {/* 「模型」那一栏是总时长减工具算出来的,不是单独测的。不标出来就是把推算冒充测量。 */}
      {stats.llmSeconds != null && <span className="opacity-60">({t("traceStatDerived")})</span>}
    </div>
  );
}

type DetailTab = "summary" | "payload" | "result" | "timing";

function pretty(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** 右侧详情:一步的全貌。分页按这一步**实际有什么**给,而不是恒定四个里空掉三个。 */
function TraceInspector({ event, turn, onClose }: { event: TraceEvent; turn: TraceTurn | undefined; onClose: () => void }) {
  const t = useI18n();
  const tabs: DetailTab[] = ["summary"];
  if (event.tool?.args !== undefined) tabs.push("payload");
  if (event.tool?.result !== undefined || event.text) tabs.push("result");
  if (event.startedAt != null || event.durationSeconds != null) tabs.push("timing");
  const [tab, setTab] = React.useState<DetailTab>("summary");
  React.useEffect(() => setTab("summary"), [event.key]);
  const active = tabs.includes(tab) ? tab : "summary";

  return (
    <aside className="grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] border-l border-border bg-panel">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <span className="text-ui-2xs uppercase tracking-[0.06em] text-muted-foreground">
          {t("traceTurnStep").replace("{turn}", String(event.turn)).replace("{step}", String(event.step))}
        </span>
        <Button variant="ghost" size="icon" className="ml-auto h-6 w-6" onClick={onClose} aria-label={t("close")}>
          <X size={13} />
        </Button>
      </div>
      <div className="flex gap-1 border-b border-border px-2 py-1.5" role="tablist">
        {tabs.map((item) => (
          <button
            key={item}
            type="button"
            role="tab"
            aria-selected={active === item}
            onClick={() => setTab(item)}
            className={cn(
              "cursor-pointer rounded-md border-0 bg-transparent px-2 py-1 text-ui-xs text-muted-foreground hover:bg-secondary hover:text-foreground",
              active === item && "bg-accent font-medium text-accent-foreground",
            )}
          >
            {t(`traceTab_${item}` as never)}
          </button>
        ))}
      </div>
      <div className="min-h-0 overflow-auto px-3 py-2">
        {active === "summary" && (
          <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-ui-xs">
            <dt className="text-muted-foreground">{t("traceFieldKind")}</dt>
            <dd className="m-0 min-w-0 break-words">{t(KIND_LABEL[event.kind] as never)}</dd>
            {event.name && (
              <>
                <dt className="text-muted-foreground">{t("traceFieldName")}</dt>
                <dd className="m-0 min-w-0 break-words font-mono">{event.name}</dd>
              </>
            )}
            <dt className="text-muted-foreground">{t("traceFieldStatus")}</dt>
            <dd className="m-0 min-w-0 break-words">{orDash(event.status ? t(`traceStatus_${event.status}` as never) : null)}</dd>
            <dt className="text-muted-foreground">{t("traceFieldDuration")}</dt>
            <dd className="m-0 min-w-0 break-words">{seconds(event.durationSeconds)}</dd>
            {turn?.prompt && (
              <>
                <dt className="text-muted-foreground">{t("traceFieldPrompt")}</dt>
                <dd className="m-0 min-w-0 break-words text-muted-foreground">{turn.prompt.slice(0, 400)}</dd>
              </>
            )}
          </dl>
        )}
        {active === "payload" && (
          <pre className="m-0 whitespace-pre-wrap break-words rounded-md border border-border bg-muted px-2 py-1.5 font-mono text-ui-xs leading-[1.5]">
            {pretty(event.tool?.args)}
          </pre>
        )}
        {active === "result" && (
          <pre className="m-0 whitespace-pre-wrap break-words rounded-md border border-border bg-muted px-2 py-1.5 font-mono text-ui-xs leading-[1.5]">
            {pretty(event.tool?.result ?? event.text)}
          </pre>
        )}
        {active === "timing" && (
          <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-ui-xs">
            <dt className="text-muted-foreground">{t("traceFieldStartedAt")}</dt>
            <dd className="m-0">{event.startedAt == null ? "—" : new Date(event.startedAt).toLocaleTimeString()}</dd>
            <dt className="text-muted-foreground">{t("traceFieldDuration")}</dt>
            <dd className="m-0">{seconds(event.durationSeconds)}</dd>
            <dt className="text-muted-foreground">{t("traceFieldTurnDuration")}</dt>
            <dd className="m-0">{seconds(turn?.durationSeconds ?? null)}</dd>
            <dt className="text-muted-foreground">{t("traceFieldFirstToken")}</dt>
            <dd className="m-0">{seconds(turn?.firstTokenSeconds ?? null)}</dd>
          </dl>
        )}
      </div>
    </aside>
  );
}

export function TraceView({
  messages,
  streamTimeline,
  usageEvents,
}: {
  messages: TraceMessage[];
  streamTimeline: AgentTimelineItem[];
  usageEvents: AgentUsageEvent[];
}) {
  const t = useI18n();
  const [mode, setMode] = React.useState<TraceTimelineMode>("sequence");
  const [query, setQuery] = React.useState("");
  const [selectedKey, setSelectedKey] = React.useState<string | null>(null);

  const turns = React.useMemo(() => buildTurns(messages, streamTimeline), [messages, streamTimeline]);
  const allEvents = React.useMemo(() => turns.flatMap((turn) => turn.events), [turns]);
  const needle = query.trim().toLowerCase();
  const visible = needle
    ? allEvents.filter((event) => `${event.name ?? ""} ${event.summary}`.toLowerCase().includes(needle))
    : allEvents;
  const selected = allEvents.find((event) => event.key === selectedKey) ?? null;

  if (allEvents.length === 0) {
    return (
      <div className="m-auto w-full max-w-[520px] p-6">
        <EmptyState icon={<ListOrdered size={20} />} title={t("traceEmptyTitle")} body={t("traceEmptyBody")} />
      </div>
    );
  }

  return (
    <div className={cn("grid min-h-0", selected ? "grid-cols-[minmax(0,1fr)_minmax(220px,280px)]" : "grid-cols-[minmax(0,1fr)]")}>
      <div className="grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)_auto]">
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-1.5">
          <div className="inline-flex h-7 items-stretch overflow-hidden rounded-full border border-border bg-panel [&>button+button]:border-l [&>button+button]:border-border" role="tablist">
            {(["sequence", "duration"] as const).map((item) => (
              <button
                key={item}
                type="button"
                role="tab"
                aria-selected={mode === item}
                onClick={() => setMode(item)}
                className={cn(
                  "inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground",
                  mode === item && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground",
                )}
              >
                {item === "duration" ? <Clock size={11} /> : <ListOrdered size={11} />}
                {t(item === "duration" ? "traceModeDuration" : "traceModeSequence")}
              </button>
            ))}
          </div>
          <Input
            className="ml-auto h-7 w-full max-w-[220px] min-w-[120px]"
            value={query}
            placeholder={t("traceSearchPlaceholder")}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>

        <TraceOverview turns={turns} mode={mode} selectedKey={selectedKey} onSelect={setSelectedKey} />

        <div className="min-h-0 overflow-auto">
          {visible.length === 0 && (
            <EmptyState
              size="compact"
              icon={<SearchX size={15} />}
              title={t("traceNoMatch")}
              action={
                <Button size="sm" variant="outline" onClick={() => setQuery("")}>
                  {t("clearSearch")}
                </Button>
              }
            />
          )}
          {visible.map((event, index) => {
            const first = index === 0 || visible[index - 1].turn !== event.turn;
            return (
              <React.Fragment key={event.key}>
                {first && (
                  // 轮头是分隔,上间距要比行距**大**才分得开。此前它比行距还小,反倒像被挤扁的一行。
                  <div className="sticky top-0 z-[1] mt-2 border-t border-border bg-panel px-3 pb-1 pt-2 text-ui-2xs uppercase tracking-[0.06em] text-muted-foreground first:mt-0 first:border-t-0">
                    {t("traceTurn").replace("{n}", String(event.turn))}
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => setSelectedKey(event.key === selectedKey ? null : event.key)}
                  className={cn(
                    // 三列定死:标签 / 内容 / 耗时。**工具名不能自成一列** —— 每一行都是独立的 grid,
                    // auto 列各算各的宽度,于是摘要的左边缘跟着工具名长短来回跳(get_workflow 那行
                    // 比 list_workflow_node_types 那行靠左一大截)。名字和摘要同流,左边缘才对得齐。
                    "grid w-full cursor-pointer grid-cols-[68px_minmax(0,1fr)_auto_16px] items-center gap-2 border-0 border-b border-border/40 bg-transparent px-3 py-1.5 text-left hover:bg-muted",
                    event.key === selectedKey && "bg-accent",
                  )}
                >
                  <span className={cn("justify-self-start rounded-full border px-1.5 py-px text-ui-2xs", KIND_TONE[event.kind])}>
                    {t(KIND_LABEL[event.kind] as never)}
                  </span>
                  <span className="min-w-0 truncate font-mono text-ui-xs text-muted-foreground">
                    {event.name && <span className="text-foreground">{event.name} </span>}
                    {event.summary}
                  </span>
                  <span className="timecode text-ui-2xs text-muted-foreground">{seconds(event.durationSeconds)}</span>
                  <ChevronRight size={12} className="justify-self-end text-muted-foreground" aria-hidden />
                </button>
              </React.Fragment>
            );
          })}
        </div>

        <TraceStatsBar turns={turns} usageEvents={usageEvents} />
      </div>

      {selected && (
        <TraceInspector
          event={selected}
          turn={turns.find((turn) => turn.turn === selected.turn)}
          onClose={() => setSelectedKey(null)}
        />
      )}
    </div>
  );
}
