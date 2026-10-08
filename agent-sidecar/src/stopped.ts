/**
 * 被「停止」掐断的那一轮,存进记忆之前改写一下 —— **停之前说出来的那段,模型下一轮要记得**。
 *
 * pi 把被中止的助手消息记成 `stopReason: "aborted"`(流式出字时停)或 `"error"`(停在工具执行中:被中止的那次请求
 * 报「This operation was aborted」)。发下一次请求时它整条丢掉这两种消息(pi-ai 的 transform-messages:「不完整的
 * 一轮不重放,从上一个完整状态重来」)。对用户按下的停止,那就错了:
 *
 *   - 界面上那段部分回答照常落库、用户看着它,模型却一个字都不记得 —— 用户说「接着刚才那样说」「第二点展开」,
 *     它从头再来;
 *   - 下一次请求里是连着两条用户消息。
 *
 * 所以只在**用户按了停止**的这一轮,把这一轮里那几条被中止的助手消息改成普通的一条:留下已经说出来的文字,末尾注明
 * 「被用户停止,没说完」;没完成的工具调用块和思考块去掉(残缺的参数、对不上签名的思考重放出去,供应商会拒);
 * 一个字都没说的,换成一句「这一轮被用户停止」,让下一条用户消息前面有一条助手消息(对话照旧一问一答交替)。
 * 已经跑完的工具调用和结果不动 —— 那是真的发生过的事。供应商回报的用量照旧留在原消息上(水位按它算)。
 */
import type { AgentMessage } from "@earendil-works/pi-agent-core";

export const STOPPED_NOTE = "(这段回答被用户停止了,没有说完。)";
export const STOPPED_EMPTY = "(这一轮被用户停止了。)";

interface Block {
  type: string;
  text?: string;
  [key: string]: unknown;
}

function cutShort(message: AgentMessage): boolean {
  const candidate = message as { role?: string; stopReason?: string };
  return candidate.role === "assistant" && (candidate.stopReason === "aborted" || candidate.stopReason === "error");
}

/** `messages` 里从 `turnStart` 起(这一轮)被中止的助手消息改成普通消息;别的原样。没有要改的就返回同一个数组。 */
export function keepWhatWasSaid(messages: AgentMessage[], turnStart: number): AgentMessage[] {
  let changed = false;
  const out = messages.map((message, index) => {
    if (index < turnStart || !cutShort(message)) return message;
    changed = true;
    const record = message as unknown as { content?: unknown; errorMessage?: string };
    const blocks = Array.isArray(record.content) ? (record.content as Block[]) : [];
    const said = blocks
      .filter((block) => block.type === "text" && typeof block.text === "string")
      .map((block) => block.text as string)
      .join("")
      .trim();
    const { errorMessage: _dropped, ...rest } = record as Record<string, unknown>;
    return {
      ...rest,
      stopReason: "stop",
      content: [{ type: "text", text: said ? `${said}\n\n${STOPPED_NOTE}` : STOPPED_EMPTY }],
    } as unknown as AgentMessage;
  });
  return changed ? out : messages;
}
