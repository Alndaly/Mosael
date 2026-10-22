/**
 * 一轮回答的**产出** —— 「做出来的」素材的认定,以及回执归属。
 *
 * 渲染侧(ToolCalls.resultDocument)把正文和产出按时间线顺序交织成一份答案文档;
 * 这里提供产出认定(producedByTool)和回执归属(receivedAssetIdsByMessage)。
 *
 * ## 「做出来的」和「碰过的」不是一回事
 *
 * 工具行明细里的 collectAssetIds 收的是**碰过的**:拿来分析的那张图、当参考的首帧、改了标签的那份。
 * 把它们也摆进答案,一次「看看这张图」的回答下面就挂着用户自己的原图。所以这里只认两种结构上就说明
 * 「这是新做出来的」的结果:
 *
 * - **任务的终态**:`{status: "succeeded", result: {...}}`(`get_job` 查到的,或确认卡执行完交回的)。
 *   产物在 `result.asset_ids`(生成,一次可能多张)或 `result.asset_id`(渲染、配音)—— 两种形状同时真实
 *   存在,和后端 receipts.produced_asset_ids 读的是同一份。
 * - **从一份素材派生出新素材**:结果顶层带 `source_asset_id`,旁边的 `asset_id` / `asset_ids` 就是派生物
 *   (切宫格、做蒙版)。`source_asset_id` 本身是原料,不算。
 * 平铺的 `asset_ids` **不收**:那是「碰过的」工具行明细的读法,一份随便什么的 id 列表摆进答案,
 * 会把用户自己的原图挂到「看看这张图」的回答下面。
 *
 * **截图不算产出**:computer_screenshot 的图是「过程里的一眼」,交回时用的是单数键 `screenshot_asset_id`
 * (只进工具行明细),不进这一份 —— 否则每一步下面都挂着一张图,看起来像答案。
 *
 * 判据看形状不看工具名单:名单要跟着工具表走,而「终态任务的 result 是产物」这件事不会变。
 *
 * ## 回执里的
 *
 * 提交了生成就结束的那一轮,图是后来到的 —— 任务跑完送回一条回执(role=job_receipt,`payload.asset_ids`
 * 由后端记下),智能体接着起一轮说「图片已生成」。那几张图属于**接下来那一轮的答案**,见 receivedAssetIdsByMessage。
 */
import type { AgentTimelineItem, ToolCall } from "@/features/agent/ToolCalls";
import { JOB_RECEIPT_ROLE, isWaitingReceipt } from "@/features/agent/JobReceiptNotice";
import { toolResultData } from "@/features/agent/toolResultShapes";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function idsAt(record: Record<string, unknown>): string[] {
  const many = Array.isArray(record.asset_ids)
    ? record.asset_ids.filter((one): one is string => typeof one === "string" && one.trim() !== "").map((one) => one.trim())
    : [];
  if (many.length > 0) return many;
  return typeof record.asset_id === "string" && record.asset_id.trim() ? [record.asset_id.trim()] : [];
}

/** 一次工具调用做出来的素材(见文件头的三条判据)。没做出来、失败、还在跑的都是空表。 */
export function producedByTool(tool: ToolCall): string[] {
  if (tool.status !== "done") return [];
  const data = toolResultData(tool.result);
  if (!isRecord(data)) return [];
  if (data.status === "succeeded" && isRecord(data.result)) return idsAt(data.result);
  if (typeof data.source_asset_id === "string") {
    return idsAt(data).filter((id) => id !== data.source_asset_id);
  }
  return [];
}

type ReceiptLike = { id: string; role: string; payload?: unknown };

function receiptAssetIds(message: ReceiptLike): string[] {
  const payload = message.payload as { asset_ids?: unknown } | null | undefined;
  return Array.isArray(payload?.asset_ids)
    ? payload.asset_ids.filter((one): one is string => typeof one === "string" && one !== "")
    : [];
}

/**
 * 回执带来的素材归给**紧接着的那一条助手消息**。
 *
 * 顺序就是因果:回执交给智能体 → 它起一轮 → 那一轮的回答在回执后面。几条回执连着到(一次提交了三张图)
 * 就都归给同一条。最后几条后面还没有助手消息的(那一轮正在跑),记在 `pending` 里 —— 正在跑的那一轮
 * 就是它们的答案。
 *
 * 还没交给智能体的回执(`undelivered`)不算:它们画在正在跑的那一轮下面,交出去之后才轮得到下一轮。
 */
export function receivedAssetIdsByMessage(messages: readonly ReceiptLike[]): {
  byMessage: Map<string, string[]>;
  pending: string[];
} {
  const byMessage = new Map<string, string[]>();
  let carried: string[] = [];
  for (const message of messages) {
    if (message.role === JOB_RECEIPT_ROLE) {
      if (!isWaitingReceipt(message)) carried = [...carried, ...receiptAssetIds(message)];
    } else if (message.role === "assistant") {
      if (carried.length > 0) byMessage.set(message.id, carried);
      carried = [];
    }
    //: 中间夹着用户消息**不清零**:有人排了话时,攒下的回执搭他那一轮的车(后端 _drain_queue_locked),
    //: 落库顺序是「回执、他那句话、回答」—— 那个回答正是智能体知道图好了之后说的。
  }
  return { byMessage, pending: carried };
}

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

export function turnWidgets(timeline: AgentTimelineItem[] | undefined): AgentWidget[] {
  const widgets: AgentWidget[] = [];
  for (const item of timeline ?? []) {
    if (item.type !== "tool") continue;
    const widget = widgetOfTool(item.tool);
    if (widget) widgets.push(widget);
  }
  return widgets;
}
