/**
 * 触发器那几件**纯的** —— 界面规则在这里,画在 `WorkflowTriggersDialog`,接口在
 * `api/domains/workflowTriggers`(路径不写在界面里,见 design/apiSeam.test.ts)。
 */

import type { WorkflowTrigger } from "@/api/client";

/**
 * 触发器能认的四档消息类型。顺序和值都和后端 `matching.TRIGGER_MESSAGE_TYPES` 一致(飞书的
 * `post`(富文本)归到 `text` —— 对用户来说它就是一段带格式的文字)。
 */
export const TRIGGER_TYPE_OPTIONS = ["text", "image", "file", "media"] as const;

/**
 * 入参能取的那几格,**顺序和值都和后端 `matching.TRIGGER_FIELDS` 对齐**(白名单那一份)。
 *
 * 界面上只让人**挑一格**,不让人手写模板:模板写法(`{{…}}`)不该出现在界面文案里
 * (见 app/messages.noTemplateSyntax.test.ts 那条棘轮),而且挑比敲不容易写错。
 * 后端仍然收完整模板(脚本、MCP 客户端那一侧可以拼前后缀)。
 */
export const TRIGGER_FIELD_OPTIONS = [
  { value: "{{trigger.text}}", labelKey: "workflowTriggersFieldText" },
  { value: "{{trigger.asset_id}}", labelKey: "workflowTriggersFieldAsset" },
  { value: "{{trigger.asset_ids}}", labelKey: "workflowTriggersFieldAssets" },
  { value: "{{trigger.file_name}}", labelKey: "workflowTriggersFieldFileName" },
  { value: "{{trigger.message_id}}", labelKey: "workflowTriggersFieldMessageId" },
  { value: "{{trigger.sender_open_id}}", labelKey: "workflowTriggersFieldSender" },
  { value: "{{trigger.chat_id}}", labelKey: "workflowTriggersFieldChatId" },
  { value: "{{trigger.bot_id}}", labelKey: "workflowTriggersFieldBotId" },
  { value: "{{trigger.message_type}}", labelKey: "workflowTriggersFieldMessageType" },
] as const;

/** 输入框里的「a, b」→ 一串干净的关键词。中英文逗号、换行都算分隔。 */
export function parseKeywords(text: string): string[] {
  return (text || "")
    .split(/[,,\n]/)
    .map((one) => one.trim())
    .filter(Boolean);
}

export function formatKeywords(keywords: readonly string[]): string {
  return (keywords || []).join(", ");
}

/**
 * 把某一格消息字段映射到某个开始节点参数上(`null` = 不映射)。
 *
 * 值就是那一格的占位符原文 —— 界面给人看的是「消息文本」这样的名字(见 TRIGGER_FIELD_OPTIONS),
 * 存下去的是模板。
 */
export function withParamMapping(
  params: Record<string, string>,
  param: string,
  field: string | null,
): Record<string, string> {
  const next = { ...params };
  if (field) next[param] = field;
  else delete next[param];
  return next;
}

/** 这张图开始节点声明的参数名。**自己算,不从 features/scheduler 借** —— 那两个功能互相引用会成环
 *  (见 features/featureBoundaries.test.ts)。 */
export function startParamNamesOf(graph: unknown): string[] {
  const nodes = isRecord(graph) && Array.isArray(graph.nodes) ? graph.nodes : [];
  const start = nodes.find((node) => isRecord(node) && node.type === "start");
  const config = isRecord(start) && isRecord(start.config) ? start.config : {};
  const params = isRecord(config.params) ? config.params : {};
  return Object.keys(params);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** 这一行事件是好是坏 —— 界面按它选颜色。 */
export function eventTone(status: string): "ok" | "warn" | "bad" | "muted" {
  if (status === "started") return "ok";
  if (status === "throttled") return "warn";
  if (status === "refused" || status === "failed") return "bad";
  return "muted";
}

/** 触发器那一行的摘要:认什么、在哪个机器人/群、限流多少。 */
export function triggerSummary(
  trigger: WorkflowTrigger,
  typeLabel: (kind: string) => string,
  anyBot: string,
): string {
  const kinds = trigger.message_types.map(typeLabel).join(" / ");
  const where = [trigger.bot_id || anyBot, trigger.chat_id].filter(Boolean).join(" · ");
  const keywords = trigger.keywords.length > 0 ? trigger.keywords.join(" / ") : "";
  return [kinds, where, keywords, `${trigger.max_runs_per_minute}/min`].filter(Boolean).join("  ·  ");
}
