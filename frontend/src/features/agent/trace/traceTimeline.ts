/**
 * 轨迹概览条:把一整个会话压成三行色块,一眼看出时间花在哪儿。
 *
 * 三条泳道 —— **输入 / 模型 / 工具**。分行不是为了好看:同一段时间里这三件事是并列发生的,
 * 挤在一行就只能看出「有事在发生」,分开才看得出「这段是在等模型,那段是在跑工具」。
 *
 * 两种投影,因为我们**不是每条记录都有绝对时间**:
 *
 * - `sequence`:每条记录等宽一格。不需要任何时间戳,永远画得出来,回答的是「按顺序发生了什么」。
 * - `duration`:按真实时长排布,回答的是「时间都去哪了」。只有带时间戳的记录参与 —— 目前是
 *   工具(逐个记了 started_at)和轮(由助手消息落库时间往前推一个轮时长)。文本、思考没有
 *   逐条时间戳,在这个投影里不出现,而不是给它们编一个位置。
 *
 * `duration` 会**压缩空闲**:两次操作之间的空当按比例挤掉。一个跑了两小时、其中真正在动的只有
 * 三分钟的会话,不压的话那三分钟就是三根看不见的头发丝。压缩量单独记着,好在轴上标出来。
 */
import type { TraceEvent, TraceTurn } from "./traceModel";

/** 0 = 输入,1 = 模型,2 = 工具。数字就是行号,渲染层照着堆。 */
export type TraceLane = 0 | 1 | 2;

export type TraceTimelineMode = "sequence" | "duration";

export type TraceSpan = {
  key: string;
  lane: TraceLane;
  /** 投影域里的起止。sequence 域是「第几格」,duration 域是毫秒。 */
  start: number;
  end: number;
  turn: number;
  kind: TraceEvent["kind"] | "turn";
  isError: boolean;
  label: string;
  /** 指回具体那一步;轮条没有对应记录,是 null。 */
  eventKey: string | null;
};

export type TraceTimelineModel = {
  start: number;
  end: number;
  spans: TraceSpan[];
  turnBoundaries: { turn: number; at: number }[];
  mode: TraceTimelineMode;
  /** duration 投影里被挤掉的空闲总量(毫秒);sequence 恒为 0。 */
  compressedIdleMs: number;
};

function laneFor(kind: TraceEvent["kind"]): TraceLane {
  if (kind === "tool") return 2;
  // 系统提示、上下文注入和提问一样,都是**送进去**的东西,不是模型产出的。
  if (kind === "user" || kind === "system" || kind === "context") return 0;
  return 1;
}

/** 等宽投影:一条记录一格。不依赖任何时间戳,所以永远有得画。 */
function sequenceTimeline(turns: TraceTurn[]): TraceTimelineModel | null {
  const spans: TraceSpan[] = [];
  const turnBoundaries: { turn: number; at: number }[] = [];
  for (const turn of turns) {
    if (turn.events.length === 0) continue;
    turnBoundaries.push({ turn: turn.turn, at: spans.length });
    for (const event of turn.events) {
      spans.push({
        key: event.key,
        lane: laneFor(event.kind),
        start: spans.length,
        end: spans.length + 1,
        turn: turn.turn,
        kind: event.kind,
        isError: event.status === "error" || event.kind === "error",
        label: event.name ?? event.summary,
        eventKey: event.key,
      });
    }
  }
  if (spans.length === 0) return null;
  return { start: 0, end: spans.length, spans, turnBoundaries, mode: "sequence", compressedIdleMs: 0 };
}

type RawSpan = TraceSpan & { rawStart: number; rawEnd: number };

/** 有绝对时间的记录:工具逐个有,轮整体有。别的没有 —— 不给它们编位置。 */
function timedSpans(turns: TraceTurn[]): RawSpan[] {
  const raw: RawSpan[] = [];
  for (const turn of turns) {
    if (turn.startedAt != null && turn.durationSeconds != null) {
      const start = turn.startedAt;
      const end = start + turn.durationSeconds * 1000;
      raw.push({
        key: `turn-${turn.turn}`,
        lane: 1,
        start,
        end,
        rawStart: start,
        rawEnd: end,
        turn: turn.turn,
        kind: "turn",
        isError: false,
        label: "",
        eventKey: null,
      });
    }
    for (const event of turn.events) {
      if (event.startedAt == null) continue;
      const start = event.startedAt;
      const end = start + (event.durationSeconds ?? 0) * 1000;
      raw.push({
        key: event.key,
        lane: laneFor(event.kind),
        start,
        end,
        rawStart: start,
        rawEnd: end,
        turn: turn.turn,
        kind: event.kind,
        isError: event.status === "error" || event.kind === "error",
        label: event.name ?? event.summary,
        eventKey: event.key,
      });
    }
  }
  return raw;
}

/**
 * 真实时长投影,挤掉空闲。
 *
 * 按开始时间扫一遍,记住「已经覆盖到哪」;下一段的起点比它晚,中间那截就是没人干活的空当,
 * 累加进 removed 并从后面所有段的坐标里减掉。用**扫描时的累计值**而不是最终值,是因为每一段
 * 该减的只是它之前发生过的空闲 —— 减总量会把前面的段拽到负数去。
 */
function durationTimeline(turns: TraceTurn[]): TraceTimelineModel | null {
  const raw = timedSpans(turns);
  if (raw.length === 0) return null;

  const ordered = [...raw].sort((a, b) => a.rawStart - b.rawStart || a.rawEnd - b.rawEnd);
  const removedBefore = new Map<string, number>();
  let removed = 0;
  let coveredUntil: number | null = null;
  for (const span of ordered) {
    if (coveredUntil != null && span.rawStart > coveredUntil) removed += span.rawStart - coveredUntil;
    removedBefore.set(span.key, removed);
    coveredUntil = coveredUntil == null ? span.rawEnd : Math.max(coveredUntil, span.rawEnd);
  }

  const spans = raw.map((span): TraceSpan => {
    const offset = removedBefore.get(span.key) ?? 0;
    return { ...span, start: span.rawStart - offset, end: span.rawEnd - offset };
  });
  const turnBoundaries = turns
    .map((turn) => {
      const own = spans.filter((span) => span.turn === turn.turn);
      return own.length > 0 ? { turn: turn.turn, at: Math.min(...own.map((span) => span.start)) } : null;
    })
    .filter((value): value is { turn: number; at: number } => value !== null);

  return {
    start: Math.min(...spans.map((span) => span.start)),
    end: Math.max(...spans.map((span) => span.end)),
    spans,
    turnBoundaries,
    mode: "duration",
    compressedIdleMs: removed,
  };
}

export function deriveTraceTimeline(turns: TraceTurn[], mode: TraceTimelineMode): TraceTimelineModel | null {
  return mode === "duration" ? durationTimeline(turns) : sequenceTimeline(turns);
}

/** 落在选中区间里的记录 key —— 概览条上刷一段,下面的列表跟着高亮。 */
export function spansInRange(model: TraceTimelineModel | null, start: number, end: number): Set<string> {
  const keys = new Set<string>();
  for (const span of model?.spans ?? []) {
    if (span.eventKey && span.start <= end && span.end >= start) keys.add(span.eventKey);
  }
  return keys;
}
