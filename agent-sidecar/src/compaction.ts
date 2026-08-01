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
const CHARS_PER_TOKEN = 3.5;

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

/**
 * 当前上下文占了多少 token。
 *
 * 以最近一条带 usage 的 assistant 消息为锚:那条 usage 的 input+output 就是供应商上次
 * 实际看到的量。锚之后的消息(新的用户提问、工具结果)才需要估算。
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
  let total = (usage.input ?? 0) + (usage.output ?? 0);
  for (let i = anchor + 1; i < messages.length; i += 1) total += estimateTokens(messages[i]);
  return total;
}

export function shouldCompact(messages: readonly Message[], contextWindow: number): boolean {
  if (!contextWindow || contextWindow <= 0) return false;
  return contextTokens(messages) > contextWindow * COMPACT_RATIO;
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
  const tokensBefore = contextTokens(messages);
  if (!options.force && !shouldCompact(messages, options.contextWindow)) {
    return { messages: [...messages], info: null };
  }
  const cut = splitPoint(messages);
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
  return {
    messages: next,
    info: { droppedMessages: cut, tokensBefore, tokensAfter: contextTokens(next), summary },
  };
}
