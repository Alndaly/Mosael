/**
 * 时间段输入的解析。
 *
 * 接受三种写法:`90`(秒)、`1:30`(分:秒)、`1:02:03`(时:分:秒)。**空就是不限** ——
 * 只填开始表示"从这里到结尾",只填结束表示"从头到这里"。
 *
 * 单独一个模块是因为它是纯判断,而输入框那种地方最容易把「没填」和「填了 0」搞混:
 * 前者是不限,后者是从第 0 秒开始 —— 对"只填结束"的那一半用户,这两件事结果完全不同。
 */

/** 解析成秒;空串或不合法返回 null(= 不限)。 */
export function parseTimecode(text: string): number | null {
  const trimmed = (text ?? "").trim();
  if (!trimmed) return null;
  const parts = trimmed.split(":").map((part) => part.trim());
  if (parts.some((part) => part === "" || !/^\d+(\.\d+)?$/.test(part))) return null;
  const numbers = parts.map(Number);
  if (numbers.length > 3) return null;
  // 从右往左:秒、分、时 —— 这样 `90`、`1:30`、`1:02:03` 走同一条路。
  return numbers.reverse().reduce((total, value, index) => total + value * 60 ** index, 0);
}

/** 这段区间能不能用。`null` = 不截取整条下载。 */
export function toSection(startText: string, endText: string): { start: number; end: number } | null {
  const start = parseTimecode(startText);
  const end = parseTimecode(endText);
  if (start === null && end === null) return null;
  const from = start ?? 0;
  // 没填结束就到结尾。用一个大得离谱的值而不是 0:yt-dlp 把 0 当"到第 0 秒",结果是空文件。
  const to = end ?? Number.MAX_SAFE_INTEGER;
  if (to <= from) return null;
  return { start: from, end: to };
}
