/**
 * 字幕面板里改起止时间:把用户敲进去的时间读成秒,以及把改好的起止换成一次 trim 的入参。
 *
 * 认这几种写法(都是时间线上的秒):`12.5`、`01:02.5`(分:秒)、`1:02:03.25`(时:分:秒),逗号当小数点
 * (SRT 的写法)。读不出来返回 null —— 由调用方把输入框还原,不去猜。
 */
export function parseCueTime(text: string): number | null {
  const trimmed = text.trim().replace(",", ".");
  if (!trimmed) return null;
  const parts = trimmed.split(":");
  if (parts.length > 3 || parts.some((part) => !/^\d+(\.\d+)?$/.test(part))) return null;
  const seconds = parts.reduce((total, part) => total * 60 + Number(part), 0);
  return Number.isFinite(seconds) ? seconds : null;
}

/** 起止 → 一次 trim(字幕片段没有素材:入点恒为 0,出点按倍速换成源时长)。起点不早于 0,终点要晚于起点。 */
export function cueTrim(
  start: number,
  end: number,
  speed = 1,
): { timeline_start: number; src_in: number; src_out: number } | null {
  if (!(start >= 0) || !(end > start)) return null;
  return { timeline_start: start, src_in: 0, src_out: (end - start) * (speed || 1) };
}
