/**
 * 按「哪一天」把一串记录分栏。
 *
 * 两条容易错的:
 *
 * 1. **后端给的是无时区标记的 UTC 串**(`2026-07-30T10:18:01.163532`,与 lib/time 同一约定)。
 *    直接 `new Date(它)` 会被当本地时间读,东八区整体偏 8 小时 —— 晚上八点后发的记录会掉进
 *    "昨天"那一栏。
 * 2. **要按用户的日历天分**,不是 UTC 的天。按 UTC 分会在本地白天的正中间切一刀。
 *
 * 合起来只有一个正确解:按 UTC 解析,按**本地**日历天归类。
 */

export type DayGroup<T> = {
  /** 本地日历天,`YYYY-MM-DD`。解析不出时间的记录归到 `""`。 */
  key: string;
  items: T[];
};

function parseBackendIso(iso: string): Date | null {
  if (!iso) return null;
  const normalized = /Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function localDayKey(date: Date): string {
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/** 分组,**保持传入顺序**(列表本来就是新→旧,分栏不该重排)。 */
export function groupByLocalDay<T>(items: readonly T[], isoOf: (item: T) => string): DayGroup<T>[] {
  const groups: DayGroup<T>[] = [];
  const byKey = new Map<string, DayGroup<T>>();
  for (const item of items) {
    const date = parseBackendIso(isoOf(item));
    const key = date ? localDayKey(date) : "";
    let group = byKey.get(key);
    if (!group) {
      group = { key, items: [] };
      byKey.set(key, group);
      groups.push(group);
    }
    group.items.push(item);
  }
  return groups;
}

export type DayKind = "today" | "yesterday" | "other" | "unknown";

/**
 * 这一天怎么称呼。**不返回「今天」这三个字** —— 文案是 i18n 的事,这里只回种类,
 * 调用方按种类取对应文案,免得纯逻辑里再塞一份中英文表。
 */
export function dayGroupOf(key: string, now: Date, locale = "zh-CN"): { kind: DayKind; text: string } {
  if (!key) return { kind: "unknown", text: "" };
  const today = localDayKey(now);
  if (key === today) return { kind: "today", text: key };

  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (key === localDayKey(yesterday)) return { kind: "yesterday", text: key };

  const [year, month, day] = key.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  const sameYear = year === now.getFullYear();
  return {
    kind: "other",
    text: date.toLocaleDateString(locale, {
      month: "long",
      day: "numeric",
      weekday: "short",
      ...(sameYear ? {} : { year: "numeric" }),
    }),
  };
}
