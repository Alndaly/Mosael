/**
 * 工具调用被写进了正文:DeepSeek 用自己的 DSML 标记写工具调用,网关没翻译成 OpenAI 的 `tool_calls`,原样当正文交回。
 *
 * 实测(CommandCode · deepseek-v4.1-flash-fast,2026-11-15),助手消息的正文里是
 *
 *     <｜｜DSML｜｜ calls>
 *     <｜｜DSML｜｜ invoke name="edit_timeline">
 *     <｜｜DSML｜｜ parameter name="sequence_id" string="true">…</｜｜DSML｜｜ parameter>
 *     </｜｜DSML｜｜ invoke>
 *     </｜｜DSML｜｜ calls>
 *
 * pi 只认结构化的工具调用:这一段被当成回答显示、落库,一个工具都没执行,这一轮当作「说完了」结束。更糟的是它进了
 * 会话历史 —— 模型下一轮照着历史接着这么写,同一个对话里越来越多。
 *
 * **这里不替它执行**:从正文里解析出动作再去执行,模型在解释里引用一段标记就会触发真动作,参数也没过供应商那边的
 * 结构化校验。做的只是:
 *
 *  · 流里一出现标记的开头就不再往外推文字(界面上不冒这串东西);
 *  · 回合结束时把标记从正文里去掉(不进历史),在消息上记下它想调哪几个工具(`mosaelLeakedToolCalls`);
 *  · 由 `stallOf` 认出这种情况,提醒模型用标准的工具调用重发一次(和「工具调用在路上丢了」同一条路)。
 *
 * 没出现标记的流原样转发。
 */
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai";
import type { AssistantMessage, AssistantMessageEvent } from "@earendil-works/pi-ai";

//: 标记里的竖线是全角的「｜」,有时成对;两侧空白可有可无。
const BAR = "[|｜]+";
const TAG = `${BAR}\\s*DSML\\s*${BAR}\\s*`;
const START = new RegExp(`<\\s*${TAG}(?:function_)?calls\\s*>`);
const INVOKE = new RegExp(`<\\s*${TAG}invoke\\s+name="([^"]+)"`, "g");
//: 流式时还没写完的开头:「<」后面只跟着竖线、空白、DSML 的前缀 —— 先压着,等下一段再判断。
const PENDING = /<\s*(?:[|｜]+\s*(?:D(?:S(?:M(?:L)?)?)?)?)?$/;

export type LeakedMessage = AssistantMessage & { mosaelLeakedToolCalls?: string[] };

/** 正文里写成标记的工具调用:标记之前那段话、它想调的工具名。没有标记时交回 null。 */
export function leakedToolCalls(text: string): { before: string; tools: string[] } | null {
  const start = text.search(START);
  if (start < 0) return null;
  const tools = [...text.slice(start).matchAll(INVOKE)].map((match) => match[1]);
  return { before: text.slice(0, start).trimEnd(), tools };
}

/** 这段正文此刻可以放心推出去的长度:标记开头之前;结尾若是一个可能还没写完的开头,也先压着;
 *  结尾的空白也压着 —— 标记前面常隔着空行,先推出去的话正文会多一截空白。块结束时一并补推。 */
function speakable(text: string): number {
  const start = text.search(START);
  const pending = text.match(PENDING);
  let end = start >= 0 ? start : pending ? text.length - pending[0].length : text.length;
  while (end > 0 && /\s/.test(text[end - 1])) end -= 1;
  return end;
}

/** 把一条结束了的助手消息正文里的标记去掉,记下它想调的工具。没有标记就原样交回。 */
export function withoutLeakedToolCalls(message: AssistantMessage): LeakedMessage {
  const tools: string[] = [];
  let changed = false;
  const content = message.content.flatMap((block): AssistantMessage["content"] => {
    if (block.type !== "text") return [block];
    const found = leakedToolCalls(block.text);
    if (!found) return [block];
    changed = true;
    tools.push(...found.tools);
    return found.before ? [{ ...block, text: found.before }] : [];
  });
  return changed ? { ...message, content, mosaelLeakedToolCalls: tools } : message;
}

/**
 * 历史里已经写进去的标记也去掉(这个修复之前存下的回复)。留着的话,模型照着历史接着把调用写进正文。
 * 只去掉文字,不记 `mosaelLeakedToolCalls` —— 那是给「这一轮刚发生」用的。
 */
export function forgetLeakedToolCalls<T>(messages: readonly T[]): T[] {
  return messages.map((message) => {
    const m = message as unknown as { role?: string; content?: unknown };
    if (m.role !== "assistant" || !Array.isArray(m.content)) return message;
    const { mosaelLeakedToolCalls: _, ...clean } = withoutLeakedToolCalls(message as unknown as AssistantMessage);
    return (clean.content === m.content ? message : clean) as unknown as T;
  });
}

type Stream = ReturnType<typeof createAssistantMessageEventStream>;

/** 包一层模型流:标记开头之后的文字不往外推,结束时把标记从消息里去掉(见模块说明)。 */
export function hidingLeakedToolCalls(
  source: AsyncIterable<AssistantMessageEvent> & { result(): Promise<AssistantMessage> },
): Stream {
  const out = createAssistantMessageEventStream();
  void (async () => {
    //: 每个正文块已经推出去多少字。
    const sent = new Map<number, number>();
    try {
      for await (const event of source) {
        if (event.type === "text_delta") {
          const block = event.partial.content[event.contentIndex];
          const text = block?.type === "text" ? block.text : "";
          const already = sent.get(event.contentIndex) ?? 0;
          const upTo = Math.max(already, speakable(text));
          if (upTo > already) out.push({ ...event, delta: text.slice(already, upTo) });
          sent.set(event.contentIndex, upTo);
        } else if (event.type === "text_end") {
          const found = leakedToolCalls(event.content);
          const content = found ? found.before : event.content;
          const already = sent.get(event.contentIndex) ?? 0;
          //: 压着的那一点(结尾的空白、最后没成为标记的「<」)在块结束时补推出去。
          if (content.length > already) {
            out.push({ type: "text_delta", contentIndex: event.contentIndex, delta: content.slice(already), partial: event.partial });
          }
          out.push({ ...event, content });
        } else if (event.type === "done") {
          out.push({ ...event, message: withoutLeakedToolCalls(event.message) });
        } else {
          out.push(event);
        }
      }
      out.end();
    } catch (error) {
      out.end();
      throw error;
    }
  })();
  return out;
}
