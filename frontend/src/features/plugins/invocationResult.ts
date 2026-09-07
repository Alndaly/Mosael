/**
 * 把调用记录里的输出整理成人能读的样子。
 *
 * **要解决的是"JSON 被编码成了字符串"。** MCP 这一侧很常见:FastMCP 把字符串返回值包进
 * `structuredContent.result`(后端 `domain/blender/bridge.py` 里有同一条注释),于是我们收到的是
 *
 *     { "result": "{\n  \"name\": \"Mosael \\u00b7 \\u4e09\\u95f4\\u5c55\\u5385\", ... }" }
 *
 * 直接 `JSON.stringify` 只会把那层转义**再转义一遍**:中文全是 `三间`、换行全是字面的
 * `\n`,整块糊成一片。而它本来是一份结构清晰的 JSON。
 *
 * 所以渲染前先把这类字符串**就地展开**成它表示的值,再统一序列化。
 */

/** 只展开这么多层。防的是构造出来的深层嵌套,以及理论上的自引用字符串。 */
const MAX_DEPTH = 6;

/** 超过这个长度的字符串不试着解析 —— 一段一百万字符的日志里恰好有个 `{` 不值得付这笔代价。 */
const MAX_PARSE_LENGTH = 200_000;

function looksLikeJson(value: string): boolean {
  const text = value.trim();
  if (text.length < 2 || text.length > MAX_PARSE_LENGTH) return false;
  // 只认对象和数组。**不认裸的数字/true/null**:`"9876"` 是端口号,把它变成数字 9876
  // 会让人以为上游返回的就是数字 —— 展示层不该悄悄改变数据的类型。
  const head = text[0];
  return (head === "{" && text.endsWith("}")) || (head === "[" && text.endsWith("]"));
}

/** 递归展开被编码成字符串的 JSON。不是 JSON 的字符串原样保留。 */
export function unwrapEncodedJson(value: unknown, depth = 0): unknown {
  if (depth >= MAX_DEPTH) return value;
  if (typeof value === "string") {
    if (!looksLikeJson(value)) return value;
    try {
      return unwrapEncodedJson(JSON.parse(value), depth + 1);
    } catch {
      // 看着像 JSON 但解不动 —— 那就是普通文本,原样给出去比吞掉好。
      return value;
    }
  }
  if (Array.isArray(value)) return value.map((item) => unwrapEncodedJson(item, depth + 1));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, unwrapEncodedJson(item, depth + 1)]),
    );
  }
  return value;
}

/**
 * 渲染用的最终文本。
 *
 * 纯字符串的输出(工具就返回一句话)保持原样输出,不给它套引号 —— 那是给人看的一句话,
 * 不是一份数据。
 */
export function formatInvocationResult(body: unknown): string {
  const unwrapped = unwrapEncodedJson(body);
  return typeof unwrapped === "string" ? unwrapped : JSON.stringify(unwrapped, null, 2);
}
