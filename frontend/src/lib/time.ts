/** 后端时间是 UTC 无时区标记的 ISO 串;补 Z 再算相对时间。 */
export function relativeTime(iso: string, locale: string): string {
  const normalized = /Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  const deltaSeconds = Math.round((new Date(normalized).getTime() - Date.now()) / 1000);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const abs = Math.abs(deltaSeconds);
  if (abs < 60) return rtf.format(Math.trunc(deltaSeconds), "second");
  if (abs < 3600) return rtf.format(Math.trunc(deltaSeconds / 60), "minute");
  if (abs < 86400) return rtf.format(Math.trunc(deltaSeconds / 3600), "hour");
  return rtf.format(Math.trunc(deltaSeconds / 86400), "day");
}
