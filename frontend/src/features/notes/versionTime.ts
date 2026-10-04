import { dayGroupOf } from "@/lib/dayGroups";
import { parseServerTime } from "@/lib/time";

/**
 * 版本记录里的时间,跟着界面语言写:中文「13:03」「今天 13:03」「10月3日 12:39」,英文「1:03 PM」「Today, 1:03 PM」。
 *
 * 后端给的是不带时区标记的 UTC 串,一律经 parseServerTime 读(直接 new Date 会被当本地时间,东八区差八小时)。
 * Intl 在英文的「1:03 PM」里放的是窄不换行空格(U+202F),统一换成普通空格 —— 文字照样不折行(短),比较也简单。
 */

const plain = (text: string) => text.replace(/ /g, " ");

function localDayKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

/** 几点几分(`seconds` 时带秒):中文 24 小时制,英文 12 小时制。 */
export function versionClock(iso: string, locale: string, seconds = false): string {
  return plain(parseServerTime(iso).toLocaleTimeString(locale, {
    hour: locale.startsWith("zh") ? "2-digit" : "numeric", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}),
    hourCycle: locale.startsWith("zh") ? "h23" : undefined,
  }));
}

/** 「今天 13:03」「昨天 12:39」「9月3日 12:39」;不是今年的带上年份。 */
export function versionMoment(iso: string, locale: string, now: Date, words: { today: string; yesterday: string }): string {
  const date = parseServerTime(iso);
  const kind = dayGroupOf(localDayKey(date), now, locale).kind;
  const day = kind === "today" ? words.today : kind === "yesterday" ? words.yesterday : date.toLocaleDateString(locale, {
    month: "long", day: "numeric", ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
  const clock = versionClock(iso, locale);
  return locale.startsWith("zh") ? `${day} ${clock}` : `${day}, ${clock}`;
}

/** 一版从几点写到几点(悬停说明里那一份,精确到秒)。开始和最后一次保存在同一分钟里就只写一个时间。 */
export function versionSpan(startedIso: string, savedIso: string, locale: string): string {
  const minutes = (parseServerTime(savedIso).getTime() - parseServerTime(startedIso).getTime()) / 60_000;
  return minutes < 1 ? versionFullTime(savedIso, locale) : `${versionFullTime(startedIso, locale)} – ${versionClock(savedIso, locale, true)}`;
}

/** 精确到秒的完整时间。 */
export function versionFullTime(iso: string, locale: string): string {
  return plain(parseServerTime(iso).toLocaleString(locale, { dateStyle: "long", timeStyle: "medium", hourCycle: locale.startsWith("zh") ? "h23" : undefined }));
}
