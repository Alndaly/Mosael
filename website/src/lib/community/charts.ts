/**
 * 手画 SVG 图表的几何部分(走势线、折线图、贡献热力图)。
 *
 * 不引图表库:官网上的图只有三种、都是只读的,几十行几何就够,换来的是这些页面不多背一个
 * 几十 KB 的包。组件在 components/community/charts.tsx,这里只算坐标 —— 纯函数,好测。
 */
import type { DailyCount } from "@/lib/community/types";

const DAY = 86_400_000;

function isoDay(time: number): string {
  return new Date(time).toISOString().slice(0, 10);
}

/**
 * 把服务给的逐日计数补齐成连续的 `days` 天(截止 `end` 那天,含)。服务可能只回有数的那几天,
 * 空着的日子画成 0,而不是把折线从周一直接连到周五。
 */
export function fillDays(points: readonly DailyCount[], days: number, end: string): DailyCount[] {
  const byDate = new Map(points.map((point) => [point.date, point.count]));
  const last = Date.parse(`${end}T00:00:00Z`);
  return Array.from({ length: days }, (_, index) => {
    const date = isoDay(last - (days - 1 - index) * DAY);
    return { date, count: byDate.get(date) ?? 0 };
  });
}

/** 服务回的最后一天;没有数据时用今天(UTC)。 */
export function lastDay(points: readonly DailyCount[], today = new Date()): string {
  return points.reduce((latest, point) => (point.date > latest ? point.date : latest), "") || isoDay(today.getTime());
}

export type Scaled = { x: number; y: number; count: number; date: string };

/** 折线的点:x 均分,y 按最大值缩放(全 0 时贴底)。上下留 `pad`,线宽不被裁掉。 */
export function scalePoints(points: readonly DailyCount[], width: number, height: number, pad = 2): Scaled[] {
  const max = Math.max(0, ...points.map((point) => point.count));
  const step = points.length > 1 ? (width - pad * 2) / (points.length - 1) : 0;
  return points.map((point, index) => ({
    x: pad + index * step,
    y: max === 0 ? height - pad : pad + (1 - point.count / max) * (height - pad * 2),
    count: point.count,
    date: point.date,
  }));
}

export function linePath(points: readonly Scaled[]): string {
  return points.map((point, index) => `${index === 0 ? "M" : "L"}${round(point.x)},${round(point.y)}`).join(" ");
}

/** 折线下面那块面积:沿线走完再落到底边闭合。 */
export function areaPath(points: readonly Scaled[], height: number): string {
  if (points.length === 0) return "";
  const first = points[0];
  const last = points[points.length - 1];
  return `${linePath(points)} L${round(last.x)},${height} L${round(first.x)},${height} Z`;
}

function round(value: number): number {
  return Math.round(value * 10) / 10;
}

/** 纵轴刻度:取 0 到一个「好看」的上界,分 `count` 段。 */
export function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0];
  const rough = max / count;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((unit) => unit * magnitude).find((candidate) => candidate >= rough) ?? rough;
  return Array.from({ length: Math.ceil(max / step) + 1 }, (_, index) => index * step);
}

export type HeatCell = { date: string; count: number; week: number; weekday: number; level: 0 | 1 | 2 | 3 | 4 };

/**
 * 贡献热力图:最近 `weeks` 周,一列一周、一行一个星期几(周日在上,和 GitHub 一样)。
 * 颜色分五档(0 是空)。
 */
export function heatmapCells(points: readonly DailyCount[], end: string, weeks = 53): HeatCell[] {
  const last = Date.parse(`${end}T00:00:00Z`);
  const lastWeekday = new Date(last).getUTCDay();
  const first = last - ((weeks - 1) * 7 + lastWeekday) * DAY;
  const byDate = new Map(points.map((point) => [point.date, point.count]));
  const total = (weeks - 1) * 7 + lastWeekday + 1;
  const counts = Array.from({ length: total }, (_, index) => byDate.get(isoDay(first + index * DAY)) ?? 0);
  // 按**不同取值的名次**分档:一天 30 次不会把其余日子都压进最浅那档。只有一种取值时都画最深。
  const distinct = [...new Set(counts.filter((count) => count > 0))].sort((a, b) => a - b);
  const rank = new Map(distinct.map((value, index) => [value, index]));
  const levelOf = (count: number): HeatCell["level"] => {
    if (count === 0) return 0;
    if (distinct.length === 1) return 4;
    return (1 + Math.round((3 * rank.get(count)!) / (distinct.length - 1))) as HeatCell["level"];
  };
  return counts.map((count, index) => ({
    date: isoDay(first + index * DAY),
    count,
    week: Math.floor(index / 7),
    weekday: index % 7,
    level: levelOf(count),
  }));
}
