/**
 * 上下文压缩:按 token 水位触发,把早期对话压成摘要而不是直接丢掉。
 *
 * 旧实现按**条数**切(>40 条留最近 24 条)。条数和 token 不成比例:30 条里夹一个巨大的
 * 工具结果照样撑爆窗口,而 41 条短消息会被白白截断。更糟的是被切掉的内容直接消失 ——
 * 用户在第 50 条问「刚才那个方案叫什么」,模型已经看不到了,却表现得像自己忘了。
 *
 * 三条设计:
 *
 * 1. **水位用供应商回报的真实数字**。pi 在每条 assistant 消息上记着这次请求的 usage,
 *    最近一条的 input+output 就是"供应商上次实际看到了多少 token" —— 比我们估算准得多。
 *    只有它之后新增的消息才需要估算。
 *
 * 2. **摘要而不是截断**。把早期消息交给同一个模型压成一段结构化摘要(已完成的事、关键
 *    结论、待办、涉及的素材/文件 id),摘要 + 最近若干条原文继续。信息密度掉了,但不再
 *    是无声地消失。
 *
 * 3. **切点落在 user 边界**。assistant 的工具调用和它的 toolResult 必须成对出现,
 *    从中间切开会让下一次请求直接被供应商拒绝(orphan tool_call)。
 *
 * 触发阈值写死 80%:留出的两成是给本轮回复和工具结果的余量。这个数用户很难判断该调多少,
 * 暴露成设置项只会变成一个没人动、动了还容易出问题的旋钮。
 */

export interface Usage {
  input?: number;
  output?: number;
  /** 缓存命中的部分。**计价另算,但照样占窗口** —— 见 contextTokens。 */
  cacheRead?: number;
}

export interface Message {
  role?: string;
  usage?: Usage;
  content?: unknown;
  [key: string]: unknown;
}

/** 超过窗口的这个比例就压缩。两成余量留给本轮的回复与工具结果。 */
export const COMPACT_RATIO = 0.8;

/** 摘要之后保留的最近消息条数。太少会丢掉正在进行的那件事的上下文,太多则压不下来。 */
export const KEEP_RECENT = 8;

/** 没有真实计量时的每 token 字符数。中英混排的粗略经验值 —— 只用于"最近几条新增了多少",
 *  估偏一点不影响判断,真实数字下一轮就由供应商纠正回来。 */
export const CHARS_PER_TOKEN = 3.5;

/** 端点没告诉我们上下文窗口时的回退。
 *
 * 云端与本地不能共用一个猜测:云端按当代常见的 128K，本机/LAN 服务按 32K。真实值仍由
 * 供应商 /models 目录或用户覆盖优先；这里仅处理两者都缺失的连接。
 *
 * **和后端 `ai/agent/host` 的两个 fallback 常量是同一套规则**,由
 * `contracts/context-meter-cases.json` 钉住:运行时压缩用这个数,界面显示另一个数,
 * 水位就会和实际行为对不上。 */
/** 未知云模型的默认窗口。2026 年主流云端模型普遍至少 128K；继续按 32K 会主动浪费容量。 */
export const FALLBACK_CONTEXT_WINDOW = 128000;
/** 本机/LAN 推理服务仍保守：它们最可能运行用户自选的小窗口模型。 */
export const LOCAL_FALLBACK_CONTEXT_WINDOW = 32000;

export function fallbackContextWindow(baseUrl: string): number {
  if (!baseUrl) return FALLBACK_CONTEXT_WINDOW;
  try {
    const hostname = new URL(baseUrl).hostname.toLowerCase().replace(/^\[|\]$/g, "");
    const octets = hostname.split(".").map(Number);
    const privateIpv4 =
      octets.length === 4 &&
      (octets[0] === 10 ||
        octets[0] === 127 ||
        (octets[0] === 192 && octets[1] === 168) ||
        (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31));
    if (hostname === "localhost" || hostname === "::1" || hostname.endsWith(".local") || privateIpv4) {
      return LOCAL_FALLBACK_CONTEXT_WINDOW;
    }
  } catch {
    // 自定义网关地址格式不标准时不擅自把它当成本地小模型。
  }
  return FALLBACK_CONTEXT_WINDOW;
}

function textOf(message: Message): string {
  const content = message.content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === "string") return part;
        if (part && typeof part === "object") {
          const record = part as Record<string, unknown>;
          if (typeof record.text === "string") return record.text;
          // 工具参数与结果往往是最占地方的那部分,不能漏算。
          return JSON.stringify(record.input ?? record.output ?? record.result ?? "");
        }
        return "";
      })
      .join(" ");
  }
  return content == null ? "" : JSON.stringify(content);
}

export function estimateTokens(message: Message): number {
  return Math.ceil(textOf(message).length / CHARS_PER_TOKEN);
}

/** 纯估算的整段大小。**衡量"压掉了多少"只能用它**,不能用 contextTokens ——
 *  后者锚定在最近一条 assistant 的 usage 上,而那个数字是"供应商上次实际看到了多少"的
 *  历史事实,不会因为我们丢掉了更早的消息而变小。用它算差值,压缩前后永远相等,
 *  界面上就是那句「腾出约 0 token」。 */
export function estimateAll(messages: readonly Message[]): number {
  return messages.reduce((sum, message) => sum + estimateTokens(message), 0);
}

/**
 * 当前上下文占了多少 token。
 *
 * 以最近一条带 usage 的 assistant 消息为锚:那条 usage 的 input+output+cacheRead 就是
 * 供应商上次实际看到的量。锚之后的消息(新的用户提问、工具结果)才需要估算。
 *
 * 语义由 `contracts/context-meter-cases.json` 钉住,后端 `domain/context_meter.py` 跑同一份
 * 语料 —— 这一份决定压不压,那一份显示还能聊多久,两边算出不同的数就会出现"水位 90% 而
 * 压缩不触发"。
 *
 * 一条 usage 都没有(首轮、或供应商不回报)就整段估算。
 */
export function contextTokens(messages: readonly Message[]): number {
  let anchor = -1;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const usage = messages[i]?.usage;
    if (messages[i]?.role === "assistant" && usage && (usage.input || usage.output)) {
      anchor = i;
      break;
    }
  }
  if (anchor < 0) return messages.reduce((sum, message) => sum + estimateTokens(message), 0);
  const usage = messages[anchor].usage!;
  // **cacheRead 也占窗口。** 它在计价上另算(便宜十倍),但"还能装多少"问的是占地方,两者
  // 没有区别。开着 prompt caching 时 input 只剩新增的一小段、绝大部分记在 cacheRead 上,
  // 漏掉它这里看到的水位就只有真实值的零头 —— 压缩迟迟不触发,直到某一轮直接超窗失败。
  let total = (usage.input ?? 0) + (usage.output ?? 0) + (usage.cacheRead ?? 0);
  for (let i = anchor + 1; i < messages.length; i += 1) total += estimateTokens(messages[i]);
  return total;
}

export function shouldCompact(messages: readonly Message[], contextWindow: number): boolean {
  if (!contextWindow || contextWindow <= 0) return false;
  return contextTokens(messages) > contextWindow * COMPACT_RATIO;
}

const MIN_TOOL_RESULT_CHARS = 320;

/**
 * 给同一轮里的后续模型调用留出回答空间。
 *
 * 轮前摘要救不了「模型先调用工具，工具一次返回几万字」：这些结果是在本轮中途才出现的。
 * pi 会按声明的 contextWindow 把 max_tokens 压到剩余空间，最坏时只剩 1 token，于是用户看到
 * 「我」「抱歉」这类碎片。这里仅裁剪交给模型的副本，Agent state 和执行记录仍保留完整结果。
 */
export function fitTurnContext(messages: readonly Message[], targetTokens: number): Message[] {
  if (targetTokens <= 0 || contextTokens(messages) <= targetTokens) return messages as Message[];

  const next = [...messages];
  const candidates: Array<{ messageIndex: number; partIndex: number; text: string }> = [];
  for (let messageIndex = 0; messageIndex < messages.length; messageIndex += 1) {
    const message = messages[messageIndex];
    if (message?.role !== "toolResult" || !Array.isArray(message.content)) continue;
    message.content.forEach((part, partIndex) => {
      if (part && typeof part === "object" && typeof (part as { text?: unknown }).text === "string") {
        const text = (part as { text: string }).text;
        if (text.length > MIN_TOOL_RESULT_CHARS) candidates.push({ messageIndex, partIndex, text });
      }
    });
  }
  candidates.sort((left, right) => right.text.length - left.text.length);

  for (const candidate of candidates) {
    const overTokens = contextTokens(next) - targetTokens;
    if (overTokens <= 0) break;
    const wantedChars = Math.max(
      MIN_TOOL_RESULT_CHARS,
      candidate.text.length - Math.ceil(overTokens * CHARS_PER_TOKEN),
    );
    if (wantedChars >= candidate.text.length) continue;
    const marker = "\n\n【工具结果内容过长已截断；完整结果仍保存在执行记录中。请缩小查询范围后再次调用。】\n\n";
    const bodyChars = Math.max(0, wantedChars - marker.length);
    const headChars = Math.ceil(bodyChars * 0.7);
    const tailChars = Math.max(0, bodyChars - headChars);
    const shortened = `${candidate.text.slice(0, headChars)}${marker}${tailChars ? candidate.text.slice(-tailChars) : ""}`;

    const originalMessage = next[candidate.messageIndex];
    const content = [...(originalMessage.content as unknown[])];
    content[candidate.partIndex] = { ...(content[candidate.partIndex] as Record<string, unknown>), text: shortened };
    next[candidate.messageIndex] = { ...originalMessage, content };
  }
  return next;
}

/**
 * 找到切点:保留最近 KEEP_RECENT 条,再往前退到最近的一条 user 消息。
 *
 * 返回 0 表示不该切 —— 全部都算"最近",没有可摘要的早期部分。切在非 user 边界会留下
 * 没有对应 assistant 调用的 toolResult,下一次请求直接被供应商拒。
 */
export function splitPoint(messages: readonly Message[]): number {
  if (messages.length <= KEEP_RECENT) return 0;
  let start = messages.length - KEEP_RECENT;
  while (start > 0 && messages[start]?.role !== "user") start -= 1;
  return start;
}

/** 交给模型的摘要指令。要的是"能接着干活"所需的东西,不是一篇读后感。 */
export const SUMMARY_PROMPT = [
  "请把上面的对话压缩成一段交接说明,供你自己在后续对话中继续使用。必须包含:",
  "1. 用户的目标与明确提出的约束(原话中的关键措辞要保留);",
  "2. 已经完成的事,以及得出的结论;",
  "3. 尚未完成、或用户明确要求接下来做的事;",
  "4. 过程中涉及的具体标识:文件路径、素材 id、工作流 id、模型名等 —— 这些后续还要用到,不能概括掉。",
  "只输出交接说明本身,不要寒暄,不要复述这条指令。",
].join("\n");

/** 摘要在新上下文里的承载形式。标成 user 而不是 system:多轮里 system 只应有一条,
 *  塞第二条 system 会让部分供应商直接报错。 */
export function summaryMessage(summary: string): Message {
  return { role: "user", content: `【早期对话的交接说明(自动压缩生成)】\n${summary}` };
}

export interface CompactionResult {
  messages: Message[];
  /** 压缩没发生时为 null。前端据此在对话流里插一条可展开的标记 —— 压缩必须被看见,
   *  否则用户不知道早期消息已经不在上下文里了。 */
  /** tokensBefore/After 是**纯估算**的整段大小,只用来说"腾出了多少";
   *  水位显示走 contextTokens(锚定真实 usage),两者算的不是同一件事。 */
  info: { droppedMessages: number; tokensBefore: number; tokensAfter: number; summary: string } | null;
}

/**
 * 压缩一次。`summarize` 由调用方注入(它要用同一个模型),便于单测。
 *
 * `force=true` 时跳过水位判断 —— 对应界面上的「立即压缩」。
 */
export async function compact(
  messages: readonly Message[],
  options: { contextWindow: number; force?: boolean; summarize: (messages: readonly Message[]) => Promise<string> },
): Promise<CompactionResult> {
  const tokensBefore = estimateAll(messages);
  if (!options.force && !shouldCompact(messages, options.contextWindow)) {
    return { messages: [...messages], info: null };
  }
  let cut = splitPoint(messages);
  if (cut <= 0 && messages.length > 1) {
    // 一个工具回包就可能把首轮撑爆，此时消息还不足 KEEP_RECENT，旧逻辑永远找不到切点。
    // 优先在下一条 user 前切；只有一个 user 时概括整轮，下一条新问题会在摘要之后追加。
    const nextUser = messages.findIndex((message, index) => index > 0 && message.role === "user");
    cut = nextUser > 0 ? nextUser : messages.length;
  }
  if (cut <= 0) return { messages: [...messages], info: null };

  const early = messages.slice(0, cut);
  let summary = "";
  try {
    summary = (await options.summarize(early)).trim();
  } catch {
    // 摘要失败不能让这一轮也失败:退回旧的截断行为,至少对话还能继续。
    // 不静默 —— info 里带上空摘要,界面照样显示"已压缩",只是没有交接说明。
    summary = "";
  }
  const next = summary ? [summaryMessage(summary), ...messages.slice(cut)] : [...messages.slice(cut)];
  const tokensAfter = estimateAll(next);
  // **压完反而更大就不算压缩**。早期部分很短时,摘要加上它的说明抬头可能比被换掉的原文还长
  // (手动点「立即整理」在短对话上就会撞到这种情况)。这时保留原文并如实报告"没压" ——
  // 界面据此说"对话还不长,暂时不需要整理",而不是显示一次让上下文变大的"整理"。
  if (tokensAfter >= tokensBefore) return { messages: [...messages], info: null };
  return {
    messages: next,
    info: { droppedMessages: cut, tokensBefore, tokensAfter, summary },
  };
}
