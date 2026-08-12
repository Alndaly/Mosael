/**
 * 工具调用的参数/结果 → 一段能读的文本。
 *
 * **显示结果本身,不是运输它的盒子。** 工具结果外面裹着一层 MCP 信封:
 *
 *     { "content": [ { "type": "text", "text": "<真正的返回值>" } ] }
 *
 * 而返回值本身往往又是一段 JSON,于是直接 `JSON.stringify(信封, null, 2)` 会把它二次转义 ——
 * 侧栏里显示的就成了满屏 `\n` 和 `\"`,一个字都读不出来(真机上 `get_workflow` 的结果正是
 * 这样)。所以这里拆一层信封,里层若是 JSON 就重新排版。
 *
 * **只在能无损拆的时候拆**:信封里出现非文本内容(图片等)时原样显示整个信封 —— 拆了会把
 * 那部分数据丢掉,而"少显示了一些东西"比"显示得难看"更糟。
 */

type TextPart = { type: "text"; text: string };

function isEnvelopeOfText(value: unknown): value is { content: TextPart[] } {
  if (typeof value !== "object" || value === null) return false;
  const content = (value as { content?: unknown }).content;
  if (!Array.isArray(content) || content.length === 0) return false;
  return content.every(
    (part) =>
      typeof part === "object" &&
      part !== null &&
      (part as { type?: unknown }).type === "text" &&
      typeof (part as { text?: unknown }).text === "string",
  );
}

/** 是 JSON 就重新排版;不是就原样返回(工具也可能只回一句话)。 */
function reformatIfJson(text: string): string {
  const trimmed = text.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return text;
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2);
  } catch {
    return text;
  }
}

export function readToolPayload(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return reformatIfJson(value);
  if (isEnvelopeOfText(value)) {
    return value.content.map((part) => reformatIfJson(part.text)).join("\n");
  }
  return JSON.stringify(value, null, 2);
}
