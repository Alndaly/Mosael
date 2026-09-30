import { NOISE_KEYS } from "@/features/agent/machineFields";

/**
 * 确认卡的载荷 → 一张**给人读**的参数表。
 *
 * 此前卡上摊的是 `JSON.stringify(payload, null, 2)`:Manim 那段几十行的 Python 成了一行
 * `"code": "import numpy as np\nfrom manim import *\n\n..."`,换行全是字面的 `\n`,要批准的
 * 那段代码恰恰是整张卡里最读不了的东西。现在按值的形状分四种摆法:
 *
 *   value  短的标量 —— 键 / 值两列
 *   text   长文本或多行文本 —— 还原真实换行的块;像代码的按语言高亮
 *   group  嵌套的对象 —— 一个带标题的小表,里面同样按这四种摆
 *   data   更深的结构(工作流图、时间线操作的列表)—— 格式化的 JSON 块
 *
 * **一样都不藏**,除了两类本来就不是给人看的东西:机器 id(NOISE_KEYS),以及卡已经在别处说了的
 * 事实(CARD_FACT_KEYS)。原始 JSON 仍在卡底的「原始数据」里,一字不少。
 */

export type PayloadField =
  | { kind: "value"; key: string; text: string }
  | { kind: "text"; key: string; text: string; language: string | null }
  | { kind: "group"; key: string; fields: PayloadField[] }
  | { kind: "data"; key: string; text: string };

/**
 * 开卡时后端写回载荷、专门给**摘要**用的事实(见 domain/agent/confirmable 的 validate):工具叫什么、
 * 用哪个连接、后果是哪一档。卡的标题和后果提示已经把它们说成了人话,参数表里再列一遍只是重复。
 * 下划线开头的(`_names`、`_count`)是同一类东西。只在顶层认 —— 用户自己的参数里叫这个名字的照常列。
 */
const CARD_FACT_KEYS = new Set(["tool_name", "tool_label", "connection", "effects"]);

/** 超过这么长的单行字符串不再挤在值那一列,单独成块。 */
const INLINE_MAX = 80;
/** 对象嵌到第几层还摊成小表;再深就是一份结构化数据,交给 JSON 块。 */
const GROUP_DEPTH = 2;

export function payloadFields(payload: unknown): PayloadField[] {
  if (!isRecord(payload)) return [];
  const visible = Object.entries(payload).filter(
    ([key]) => !NOISE_KEYS.has(key) && !CARD_FACT_KEYS.has(key) && !key.startsWith("_"),
  );
  // 只剩一个对象(插件工具的载荷就是 `{arguments: {...}}` 加上面那些事实):
  // 直接摊它的字段,不让整张表缩在一个叫 arguments 的小标题下面。
  if (visible.length === 1 && isRecord(visible[0][1])) return fieldsOf(visible[0][1], 0);
  return fieldsOf(Object.fromEntries(visible), 0);
}

function fieldsOf(record: Record<string, unknown>, depth: number): PayloadField[] {
  const fields = Object.entries(record).map(([key, value]) => field(key, value, depth));
  // 短的在上、成块的在下:键值表是扫一眼的东西,别被一段长代码从中间劈开。
  return [...fields.filter((one) => one.kind === "value"), ...fields.filter((one) => one.kind !== "value")];
}

function field(key: string, value: unknown, depth: number): PayloadField {
  if (typeof value === "string") {
    if (value.includes("\n") || value.length > INLINE_MAX) {
      return { kind: "text", key, text: value, language: guessLanguage(key, value) };
    }
    return { kind: "value", key, text: value };
  }
  if (value == null || typeof value !== "object") return { kind: "value", key, text: String(value) };
  if (Array.isArray(value) && value.every((item) => item == null || typeof item !== "object")) {
    const joined = value.map(String).join(", ");
    if (joined.length <= INLINE_MAX) return { kind: "value", key, text: joined };
  }
  if (isRecord(value) && depth < GROUP_DEPTH) return { kind: "group", key, fields: fieldsOf(value, depth + 1) };
  return { kind: "data", key, text: JSON.stringify(value, null, 2) };
}

/** 键名说它是代码的(`code`、`script`、`xxx_code`)。 */
const CODE_KEY = /^(code|script|source|snippet|python|py)$|_code$/i;
const MARKDOWN_KEY = /^(markdown|md)$|_markdown$/i;

/**
 * 按键名和内容猜语言。**猜不准就是 null**(按普通文字显示,保留换行) —— 提示词、文案被错当成
 * 代码染上颜色,比不染更难读。键名说是代码的,内容又认不出来,就按 Python:应用里「代码」一词
 * 说的就是它(代码节点、本机执行、Blender、Manim)。
 */
export function guessLanguage(key: string, text: string): string | null {
  const body = text.trim();
  if (MARKDOWN_KEY.test(key)) return "markdown";
  if (/^[[{]/.test(body)) {
    try {
      JSON.parse(body);
      return "json";
    } catch {
      // 不是 JSON,往下看。
    }
  }
  // Python 的这几种行首足够独特,不看键名也认;别的语言只在键名说它是代码时才猜 ——
  // 「Update the timeline…」这种提示词不该因为像 SQL 就被染色。
  if (/^(import \w|from [\w.]+ import |def \w+\(|class \w+[:(])/m.test(body)) return "python";
  if (!CODE_KEY.test(key)) return null;
  if (/^(const|let|function|export|import) |=> ?[{(]/m.test(body)) return "javascript";
  return "python";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value);
}
