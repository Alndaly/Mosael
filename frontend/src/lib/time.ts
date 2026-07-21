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

export function formatElapsedSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0s";
  if (seconds < 60) {
    return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return rest > 0 ? `${minutes}m ${rest}s` : `${minutes}m`;
}

export function elapsedSecondsBetween(startIso: string | null | undefined, endIso: string | Date | null | undefined): number | null {
  if (!startIso || !endIso) return null;
  const start = new Date(/Z|[+-]\d\d:?\d\d$/.test(startIso) ? startIso : `${startIso}Z`).getTime();
  const end =
    endIso instanceof Date
      ? endIso.getTime()
      : new Date(/Z|[+-]\d\d:?\d\d$/.test(endIso) ? endIso : `${endIso}Z`).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  return Math.max(0, (end - start) / 1000);
}
