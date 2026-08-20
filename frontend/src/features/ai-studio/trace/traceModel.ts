/**
 * 会话轨迹的数据层:把「一条条聊天消息」摊平成「一步步执行」。
 *
 * 对话视图回答的是「它说了什么」,轨迹回答的是**「它做了什么、花在哪儿」** —— 同一份数据,
 * 两种读法。现在这些信息其实都已经落库了(助手消息 payload 里的 timeline、工具卡上的
 * started_at/duration、按消息归集的用量事件),只是散在各条气泡里,想看清一轮里跑了几步、
 * 时间是耗在模型还是工具上,只能一条条展开数。
 *
 * **未知一律是 null,不是 0。** 这里每个统计量都可能没有底数:没有用量事件时 token 不是零而是
 * 没记;工具还在跑时它没有时长。把未知写成 0,界面上就成了「这轮没花 token」「这步是瞬间完成
 * 的」—— 一个看起来精确的假数字,比一个空着的位置糟得多。渲染层据此决定「不显示这一项」。
 */
import type { AgentTimelineItem, ToolCall } from "@/components/agent/ToolCalls";
import type { AgentUsageEvent } from "@/features/ai-studio/messageUsage";
import { summarizeMessageUsage } from "@/features/ai-studio/messageUsage";

/** 轨迹里的一步。kind 决定行首那个标签,也决定 Inspector 里能看什么。 */
export type TraceEventKind = "system" | "context" | "user" | "text" | "thinking" | "tool" | "subtool" | "compaction" | "error";

export type TraceEvent = {
  /** 稳定 key:消息 id + 轮内序号。流式那一轮用 "stream" 作消息 id。 */
  key: string;
  /** 第几轮(1 起)。一轮 = 一条用户消息 + 它引出的全部执行。 */
  turn: number;
  /** 轮内第几条记录(1 起)。提问算第一条 —— 它是这一轮的由头。 */
  step: number;
  kind: TraceEventKind;
  messageId: string;
  /** 行内那句摘要:工具是「参数 → 结果」,文本是首行。渲染层负责截断。 */
  summary: string;
  /** 工具名;只有 kind === "tool" 有。 */
  name?: string;
  tool?: ToolCall;
  text?: string;
  /** 绝对开始时间(epoch ms)。**只有工具有真值** —— 别的事件后端没有逐条打时间戳。 */
  startedAt: number | null;
  durationSeconds: number | null;
  status?: "running" | "done" | "error";
};

export type TraceTurn = {
  turn: number;
  /** 这一轮的提问。可能没有(会话以助手消息开头的历史数据)。 */
  prompt: string;
  events: TraceEvent[];
  /** 这一轮涉及的消息 id —— 用量事件按 agent_message_id 归集,靠它把 token 摊回到轮上。 */
  messageIds: string[];
  /** 这一轮的 token 明细。没有用量事件就是 null(未知),不是全零。 */
  usage: { input: number | null; output: number | null; cacheRead: number | null } | null;
  /** 整轮墙钟耗时,来自助手消息的 usage.duration_seconds。 */
  durationSeconds: number | null;
  /** 首 token 延迟(秒),来自 usage.first_token_seconds。老会话没有这个键 —— 那是未知,不是 0。 */
  firstTokenSeconds: number | null;
  /** 轮开始的绝对时间(epoch ms):助手消息落库时间往前推一个轮时长。 */
  startedAt: number | null;
  toolSeconds: number | null;
};

export type TraceStats = {
  turns: number;
  steps: number;
  toolCalls: number;
  failedToolCalls: number;
  /** 工具占用的墙钟时间;一个工具都没有时是 0(这是真的零,不是未知)。 */
  toolSeconds: number | null;
  /** 全部轮次的墙钟总和。没有一轮带耗时就是 null。 */
  totalSeconds: number | null;
  /** 总时长减去工具时长 —— **推算值**,不是独立测量的。渲染层要如实标注。 */
  llmSeconds: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  cacheReadTokens: number | null;
  /** 命中率 = 缓存读 /(缓存读 + 新读入)。没有缓存字段的供应商这里是 null。 */
  cacheHitRate: number | null;
  /** 首 token 延迟的平均值,只统计**记到了**这个数的轮次。 */
  firstTokenSeconds: number | null;
  /** 参与上面那个平均的轮数 —— 界面据此说明「基于 N 轮」,而不是让人以为是全部。 */
  firstTokenSamples: number;
  /** 出字速率 = 输出 token /(轮时长 − 首 token 延迟)。两个数缺一个就是 null。 */
  outputTokensPerSecond: number | null;
};

/** 一行摘要:字符串取首行,对象取第一个非空字符串值,再不行就 JSON。 */
export function oneLine(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value.split("\n").find((line) => line.trim()) ?? "";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    const first = value.find((item) => typeof item === "string" && item.trim());
    return typeof first === "string" ? first : `[${value.length}]`;
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return "";
    }
  }
  return "";
}

function parseTime(value: unknown): number | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** 工具那一行:参数摘要 → 结果摘要。两头都可能为空,箭头只在两头都有时出现。 */
function toolSummary(tool: ToolCall): string {
  const args = oneLine(tool.args);
  const result = tool.status === "error" ? oneLine(tool.result) : oneLine(tool.result);
  if (args && result) return `${args} → ${result}`;
  return args || result;
}

type TraceMessage = {
  id: string;
  role: string;
  content: string;
  error?: string | null;
  created_at: string;
  payload: unknown;
};

type MessagePayload = {
  timeline?: AgentTimelineItem[];
  /** 用户消息:随消息一起发出去的上下文(编辑器状态等)。模型收到的是它和正文拼起来的那一份。 */
  context?: string;
  /** 助手消息:这一轮的系统提示快照,**只在它变了的那一轮才有**(见 host._prompt_snapshot)。 */
  prompt?: { system?: string; hash?: string };
  usage?: { duration_seconds?: number; first_token_seconds?: number };
  compaction?: unknown;
};

function readPayload(message: TraceMessage): MessagePayload {
  return (message.payload ?? {}) as MessagePayload;
}

/**
 * 摊平成轮次。
 *
 * 分轮的依据是**用户消息**:每遇到一条 user 就开新的一轮,后续的助手/系统消息都归到它名下。
 * 会话可能以助手消息开头(历史数据、系统提示),那种情况下先开一轮无提问的轮 —— 丢掉它们
 * 等于轨迹里凭空少几步。
 */
export function buildTurns(
  messages: TraceMessage[],
  streamTimeline: AgentTimelineItem[] = [],
  usageEvents: AgentUsageEvent[] = [],
): TraceTurn[] {
  const turns: TraceTurn[] = [];
  let current: TraceTurn | null = null;

  const openTurn = (prompt: string): TraceTurn => {
    const turn: TraceTurn = {
      turn: turns.length + 1,
      prompt,
      events: [],
      messageIds: [],
      usage: null,
      durationSeconds: null,
      firstTokenSeconds: null,
      startedAt: null,
      toolSeconds: null,
    };
    turns.push(turn);
    // 提问本身也是轨迹上的一条记录 —— 它是这一轮的由头,读轨迹时第一个要看的就是它。
    // 无提问的轮(历史数据里以助手消息开头的会话)不造一条空的出来。
    if (prompt) {
      turn.events.push({
        key: `turn-${turn.turn}:user`,
        turn: turn.turn,
        step: 1,
        kind: "user",
        messageId: "",
        summary: oneLine(prompt),
        text: prompt,
        startedAt: null,
        durationSeconds: null,
      });
    }
    return turn;
  };

  const pushTimeline = (turn: TraceTurn, timeline: AgentTimelineItem[] | undefined, messageId: string) => {
    for (const item of timeline ?? []) {
      if (item.type === "tool") {
        const tool = item.tool;
        turn.events.push({
          key: `${messageId}:${turn.events.length}`,
          turn: turn.turn,
          step: turn.events.length + 1,
          kind: "tool",
          messageId,
          name: tool.name,
          summary: toolSummary(tool),
          tool,
          startedAt: parseTime(tool.usage?.started_at),
          durationSeconds: typeof tool.usage?.duration_seconds === "number" ? tool.usage.duration_seconds : null,
          status: tool.status,
        });
      } else if (item.type === "subtool") {
        // 子智能体内部的一步。**耗时不计入工具总时长**(见 traceStats):它发生在父
        // run_subagent 的计时里,双计会把「工具 2m」虚增将近一倍。
        const tool = item.tool;
        turn.events.push({
          key: `${messageId}:${turn.events.length}`,
          turn: turn.turn,
          step: turn.events.length + 1,
          kind: "subtool",
          messageId,
          name: tool.name,
          summary: toolSummary(tool),
          tool,
          startedAt: parseTime(tool.usage?.started_at),
          durationSeconds: typeof tool.usage?.duration_seconds === "number" ? tool.usage.duration_seconds : null,
          status: tool.status,
        });
      } else if (item.type === "thinking") {
        turn.events.push({
          key: `${messageId}:${turn.events.length}`,
          turn: turn.turn,
          step: turn.events.length + 1,
          kind: "thinking",
          messageId,
          summary: oneLine(item.text),
          text: item.text,
          startedAt: null,
          durationSeconds: null,
        });
      } else if (item.text) {
        turn.events.push({
          key: `${messageId}:${turn.events.length}`,
          turn: turn.turn,
          step: turn.events.length + 1,
          kind: "text",
          messageId,
          summary: oneLine(item.text),
          text: item.text,
          startedAt: null,
          durationSeconds: null,
        });
      }
    }
  };

  for (const message of messages) {
    const payload = readPayload(message);
    if (message.role === "user") {
      current = openTurn(message.content);
      current.messageIds.push(message.id);
      // 上下文注入单独成条:它不是用户打的字,但模型收到的确实是「正文 + 这一段」。
      // 混在提问里看不出来,而「它凭什么知道我选中了哪个素材」的答案往往就在这儿。
      if (payload.context) {
        current.events.push({
          key: `${message.id}:context`,
          turn: current.turn,
          step: current.events.length + 1,
          kind: "context",
          messageId: message.id,
          summary: oneLine(payload.context),
          text: payload.context,
          startedAt: null,
          durationSeconds: null,
        });
      }
      continue;
    }
    if (!current) current = openTurn("");

    if (message.role === "system") {
      // 压缩标记:它不是一步执行,但「从这里往前被整理过」是读轨迹时必须看见的事。
      if (payload.compaction) {
        current.events.push({
          key: `${message.id}:compaction`,
          turn: current.turn,
          step: current.events.length + 1,
          kind: "compaction",
          messageId: message.id,
          summary: "",
          startedAt: parseTime(message.created_at),
          durationSeconds: null,
        });
      }
      continue;
    }

    current.messageIds.push(message.id);
    // 系统提示排在这一轮的执行之前 —— 它是输入,不是产物。只有变化的那一轮才有这一条。
    if (payload.prompt?.system) {
      current.events.push({
        key: `${message.id}:system`,
        turn: current.turn,
        step: current.events.length + 1,
        kind: "system",
        messageId: message.id,
        summary: oneLine(payload.prompt.system),
        text: payload.prompt.system,
        startedAt: null,
        durationSeconds: null,
      });
    }

    pushTimeline(current, payload.timeline, message.id);

    // 失败轮:错误本身就是这一轮的结局,得在轨迹上占一行,而不是让这轮看起来只是短了点。
    if (message.error) {
      current.events.push({
        key: `${message.id}:error`,
        turn: current.turn,
        step: current.events.length + 1,
        kind: "error",
        messageId: message.id,
        summary: oneLine(message.error),
        text: message.error,
        startedAt: null,
        durationSeconds: null,
        status: "error",
      });
    }
    // 没有 timeline 的老消息(payload 里只有 content):正文本身就是这一轮唯一的一步。
    if (!payload.timeline?.length && !message.error && message.content) {
      current.events.push({
        key: `${message.id}:content`,
        turn: current.turn,
        step: current.events.length + 1,
        kind: "text",
        messageId: message.id,
        summary: oneLine(message.content),
        text: message.content,
        startedAt: null,
        durationSeconds: null,
      });
    }

    const firstToken = payload.usage?.first_token_seconds;
    if (typeof firstToken === "number" && current.firstTokenSeconds == null) {
      current.firstTokenSeconds = firstToken;
    }
    const duration = payload.usage?.duration_seconds;
    if (typeof duration === "number") {
      current.durationSeconds = (current.durationSeconds ?? 0) + duration;
      // 轮开始 = 助手消息落库时间往前推一个轮时长。比用 user 消息的时间准:排队的消息可能
      // 在几分钟前就打好了,那段等待不属于这一轮的执行。
      const finished = parseTime(message.created_at);
      if (finished != null && current.startedAt == null) current.startedAt = finished - duration * 1000;
    }
  }

  // 正在跑的这一轮:流里的时间线还没落库,但它恰恰是最该被看见的一段。
  if (streamTimeline.length > 0) {
    const turn = current ?? openTurn("");
    pushTimeline(turn, streamTimeline, "stream");
  }

  for (const turn of turns) {
    // 轮级 token:把这一轮涉及的消息对应的用量事件加起来。一条都没有 = 未知,不是 0 ——
    // 会话可能根本没开计量,那和「这一轮没花 token」是两回事。
    const own = usageEvents.filter((event) => event.agent_message_id && turn.messageIds.includes(event.agent_message_id));
    if (own.length > 0) {
      const summary = summarizeMessageUsage(own);
      turn.usage = {
        input: summary.inputTokens,
        output: summary.outputTokens,
        cacheRead: cacheTokens(own, "cache_read"),
      };
    }
    const durations = turn.events
      .filter((event) => event.kind === "tool")
      .map((event) => event.durationSeconds)
      .filter((value): value is number => typeof value === "number");
    turn.toolSeconds = durations.length > 0 ? durations.reduce((a, b) => a + b, 0) : null;
  }
  return turns;
}

/**
 * 会话级统计。
 *
 * `llmSeconds` 是**减出来的**:总墙钟减去工具占用。它不是独立测量 —— 后端只逐轮记了总耗时、
 * 逐工具记了各自耗时,中间没有第三个计时器。绝大多数时候这个差就是「等模型」,但它也吃掉了
 * 序列化、落库这些零碎。渲染层把它标成「模型(推算)」,不假装它是测出来的。
 *
 * 首 token 延迟、每秒 token 数**不在这里** —— 后端没记这两个数,凑一个出来只会得到一个看着
 * 精确的假数字。要它们得先在 host 里打点。
 */
export function traceStats(turns: TraceTurn[], usageEvents: AgentUsageEvent[]): TraceStats {
  const events = turns.flatMap((turn) => turn.events);
  // **只算顶层工具**:subtool 的时间发生在父 run_subagent 的计时里,一起累计会把
  // 「工具 2m」虚增将近一倍 —— 同一段时间被父子各记了一遍。
  const toolEvents = events.filter((event) => event.kind === "tool");

  const turnDurations = turns
    .map((turn) => turn.durationSeconds)
    .filter((value): value is number => typeof value === "number");
  const totalSeconds = turnDurations.length > 0 ? turnDurations.reduce((a, b) => a + b, 0) : null;

  const toolDurations = toolEvents
    .map((event) => event.durationSeconds)
    .filter((value): value is number => typeof value === "number");
  const toolSeconds = toolEvents.length === 0 ? 0 : toolDurations.length > 0 ? toolDurations.reduce((a, b) => a + b, 0) : null;

  // 两个数都得有才谈得上相减。夹到 0:工具可能并行,减出负数只说明"几乎全在工具里"。
  const llmSeconds =
    totalSeconds != null && toolSeconds != null ? Math.max(0, totalSeconds - toolSeconds) : null;

  const usage = summarizeMessageUsage(usageEvents);
  const hasUsage = usageEvents.length > 0;
  const cacheReadTokens = cacheTokens(usageEvents, "cache_read");
  const inputTokens = hasUsage ? usage.inputTokens : null;
  const outputTokens = hasUsage ? usage.outputTokens : null;
  const cacheBase = (cacheReadTokens ?? 0) + (inputTokens ?? 0);

  // 首 token:只有记到了的轮才参与平均。混入没记的轮(当 0 算)会把这个数拉向零,
  // 而那恰恰是最容易被当成「很快」误读的方向。
  const firstTokens = turns
    .map((turn) => turn.firstTokenSeconds)
    .filter((value): value is number => typeof value === "number");
  // 出字时间 = 轮时长 − 首 token 延迟。**两个数都得来自同一轮**,否则这个商没有意义。
  let decodeSeconds = 0;
  for (const turn of turns) {
    if (typeof turn.durationSeconds === "number" && typeof turn.firstTokenSeconds === "number") {
      decodeSeconds += Math.max(0, turn.durationSeconds - turn.firstTokenSeconds);
    }
  }

  return {
    turns: turns.length,
    steps: events.length,
    toolCalls: toolEvents.length,
    failedToolCalls: toolEvents.filter((event) => event.status === "error").length,
    toolSeconds,
    totalSeconds,
    llmSeconds,
    inputTokens,
    outputTokens,
    cacheReadTokens,
    // 一个 token 都没有的会话谈不上命中率 —— 那是「还没跑过」,不是「命中 0%」。
    cacheHitRate: cacheReadTokens != null && cacheBase > 0 ? cacheReadTokens / cacheBase : null,
    firstTokenSeconds: firstTokens.length > 0 ? firstTokens.reduce((a, b) => a + b, 0) / firstTokens.length : null,
    firstTokenSamples: firstTokens.length,
    outputTokensPerSecond: outputTokens != null && outputTokens > 0 && decodeSeconds > 0 ? outputTokens / decodeSeconds : null,
  };
}

/**
 * 用量事件里的缓存 token。后端按 cache_read_token / cache_write_token 计量(domain/usage)。
 *
 * **一条都没报过就是 null,不是 0。** 不是每个供应商都回缓存字段;当 0 算的话,命中率会稳稳
 * 显示成「0%」—— 一个看起来是结论的数字,实际上只是「这家没告诉我们」。这两句话得让人分得开。
 */
function cacheTokens(events: AgentUsageEvent[], prefix: "cache_read" | "cache_write"): number | null {
  let total = 0;
  let reported = false;
  for (const event of events) {
    for (const key of [`${prefix}_token`, `${prefix}_tokens`]) {
      const value = (event.units ?? {})[key];
      if (typeof value === "number" && Number.isFinite(value)) {
        total += value;
        reported = true;
        break;
      }
    }
  }
  return reported ? Math.round(total) : null;
}
