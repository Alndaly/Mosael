/**
 * **答案区显示什么,由智能体自己决定**(维护者 2026-10-22)。
 *
 * 渲染侧(ToolCalls.resultDocument)只把智能体最后那段**正文**摆进答案区 —— 正文就是它流式交回来的
 * markdown:要展示图就写 `![说明](mosael-asset:<asset_id>)`(前端换成本地可取的带 token 地址,见
 * components/markdown/assetRefs),要一小块界面就写内嵌 HTML(Streamdown 会清洗后渲染)。
 *
 * 所以这个模块不再回答「哪个工具算做出了产出、该织进答案」——那条固定规则删掉了:工具做出来的素材、
 * 回执带来的图都只留在**过程**里(工具行明细、回执那一步)。同一张图在正文和结果区各出现一次是同一件
 * 事画两遍,而「图在文上还是文下」该由写字的人定。
 *
 * 这里只剩一件渲染侧真要的事:认出 `show_widget` 的小界面,让它画在**发起它的那一行明细里**。
 */
import type { ToolCall } from "@/features/agent/ToolCalls";

/** 智能体给的一块小界面(`show_widget` 工具,见后端 mcp_server.show_widget)。 */
export type AgentWidget = { id: string; title: string; html: string };

export const SHOW_WIDGET_TOOL = "show_widget";

/**
 * 这一轮里智能体给出的小界面。只认**成功了的** `show_widget`:后端校验没过(超长、空)的那次是失败的工具
 * 调用,原因留在工具行里,不在答案里摆一个坏掉的框。
 *
 * 内容取自调用的参数,不取自结果:结果只回一句「已显示」,把几十 KB 的 HTML 原样再回给模型一遍是白花上下文。
 */
/** 这一次 `show_widget` 调用给出的合法小界面;没成功/没内容的返回 null。 */
export function widgetOfTool(tool: ToolCall): AgentWidget | null {
  if (tool.name !== SHOW_WIDGET_TOOL || tool.status !== "done") return null;
  const args = tool.args as { title?: unknown; html?: unknown } | null | undefined;
  if (typeof args?.html !== "string" || !args.html.trim()) return null;
  return { id: tool.id, title: typeof args.title === "string" ? args.title : "", html: args.html };
}
