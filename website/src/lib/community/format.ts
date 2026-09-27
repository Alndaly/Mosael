import { HTML_LANG, type Locale } from "@/i18n/config";

/**
 * 数字与日期的写法。
 *
 * 日期一律按 **UTC** 格式化:服务端渲染和浏览器水合要写出同一串字,否则 React 报不一致 ——
 * 而社区页上的日期只到天,差几个小时的时区无关紧要。要精确到分钟的地方(会话的最后使用时间)
 * 只在浏览器里渲染,用访客自己的时区(`local: true`)。
 */
export function formatCount(value: number, locale: Locale): string {
  return new Intl.NumberFormat(HTML_LANG[locale], { notation: value >= 10_000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value);
}

export function formatDate(value: string, locale: Locale): string {
  const time = Date.parse(value);
  if (Number.isNaN(time)) return value;
  return new Intl.DateTimeFormat(HTML_LANG[locale], { dateStyle: "medium", timeZone: "UTC" }).format(time);
}

export function formatDateTime(value: string, locale: Locale): string {
  const time = Date.parse(value);
  if (Number.isNaN(time)) return value;
  return new Intl.DateTimeFormat(HTML_LANG[locale], { dateStyle: "medium", timeStyle: "short" }).format(time);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`;
}

/** `{count}` 这类占位换成值。文案在 messages.ts 里,数字在这里填。 */
export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) => (key in values ? String(values[key]) : match));
}
