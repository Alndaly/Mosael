/**
 * 工具返回的图片 —— 让模型**看见**自己做出来的东西,又不让它们把上下文撑爆。
 *
 * 建模、摆场景时,模型改一步就看一眼(view_scene / Blender 截图),一轮下来可能几十张图。
 * 全留着的话,每次调用模型都要把它们重发一遍:一张 960×540 的图约一千多 token,二十张就是
 * 两三万 —— 而有用的只有最近那几张,更早的画面描述的是已经被改掉的状态。所以:
 *
 *   - 轮内只留最近 `RECENT_TOOL_IMAGES` 张,更早的换成一句说明(`keepRecentToolImages`);
 *   - 轮结束后**全部**换成说明再存进会话状态(`dropToolImages`):下一轮重发上一轮的截图
 *     没有意义,要看就重新看一眼当前的样子;
 *   - 模型本身看不了图的,一张都不发(发了供应商会直接报错),换成说明让它知道发生了什么。
 *
 * 用户自己贴的图不在这里处理 —— 它们在 user 消息里,是对话内容本身,不是某次检查的中间结果。
 */
import type { AgentMessage } from "@earendil-works/pi-agent-core";

export const RECENT_TOOL_IMAGES = 4;

const OMITTED_OLD = "[较早的画面已省略 —— 场景可能已经变了,需要时重新查看]";
const OMITTED_PAST_TURN = "[上一轮查看过的画面,未保留 —— 需要时重新查看]";
const OMITTED_BLIND = "[工具返回了图片,但当前模型不支持看图,未发送]";

interface Block {
  type: string;
  [key: string]: unknown;
}

function isToolResult(message: AgentMessage): message is AgentMessage & { content: Block[] } {
  const candidate = message as { role?: string; content?: unknown };
  return candidate.role === "toolResult" && Array.isArray(candidate.content);
}

/** 从新到旧数图片,第 `keep` 张之后的换成 `note`。没有要换的就原样返回同一个数组。 */
function replaceImages(messages: AgentMessage[], keep: number, note: string): AgentMessage[] {
  let seen = 0;
  let changed = false;
  const out = [...messages];
  for (let index = out.length - 1; index >= 0; index -= 1) {
    const message = out[index];
    if (!isToolResult(message) || !message.content.some((block) => block.type === "image")) continue;
    const content = message.content.map((block) => {
      if (block.type !== "image") return block;
      seen += 1;
      if (seen <= keep) return block;
      changed = true;
      return { type: "text", text: note };
    });
    out[index] = { ...message, content } as unknown as AgentMessage;
  }
  return changed ? out : messages;
}

/** 轮内:每次调用模型前,只留最近几张;看不了图的模型一张不留。 */
export function keepRecentToolImages(messages: AgentMessage[], vision: boolean): AgentMessage[] {
  return vision
    ? replaceImages(messages, RECENT_TOOL_IMAGES, OMITTED_OLD)
    : replaceImages(messages, 0, OMITTED_BLIND);
}

/** 轮末:存进会话状态之前,工具图片一张不留。 */
export function dropToolImages(messages: AgentMessage[]): AgentMessage[] {
  return replaceImages(messages, 0, OMITTED_PAST_TURN);
}
