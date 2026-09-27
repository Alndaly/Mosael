import type { Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { areaPath, fillDays, heatmapCells, lastDay, linePath, niceTicks, scalePoints } from "@/lib/community/charts";
import { fill, formatCount, formatDate } from "@/lib/community/format";
import type { DailyCount } from "@/lib/community/types";

/**
 * 三种只读图:下载走势(详情页右栏)、逐日折线(统计页)、贡献热力图(作者主页)。
 *
 * 服务端直接画成 SVG,不进浏览器的 JS 包。悬停看数用 SVG 的 `<title>`(读屏软件也读得到);
 * 颜色一律取主题变量,明暗两档自己成立。
 */

export function Sparkline({ locale, points, days = 30, label }: { locale: Locale; points: DailyCount[]; days?: number; label: string }) {
  const t = getMessages(locale).community;
  const series = fillDays(points, days, lastDay(points));
  const total = series.reduce((sum, point) => sum + point.count, 0);
  if (total === 0) return <p className="m-0 text-sm text-muted-foreground">{t.noTrend}</p>;
  const width = 280;
  const height = 56;
  const scaled = scalePoints(series, width, height, 3);
  const slot = width / series.length;
  return (
    <figure className="m-0 grid gap-2">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-14 w-full overflow-visible" aria-label={`${label}: ${formatCount(total, locale)}`}>
        <path d={areaPath(scaled, height)} className="fill-primary/12" />
        <path d={linePath(scaled)} className="fill-none stroke-primary" strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        {scaled.map((point, index) => (
          <rect key={point.date} x={index * slot} y={0} width={slot} height={height} className="fill-transparent hover:fill-primary/8">
            <title>{`${formatDate(point.date, locale)} · ${formatCount(point.count, locale)}`}</title>
          </rect>
        ))}
      </svg>
      <figcaption className="flex justify-between text-xs text-muted-foreground">
        <span>{formatDate(series[0].date, locale)}</span>
        <span className="font-mono tabular-nums text-foreground">{formatCount(total, locale)}</span>
      </figcaption>
    </figure>
  );
}

/** 统计页的一张逐日折线:纵轴几条刻度线,横轴只标首尾两天。 */
export function LineChart({ locale, points, days, title }: { locale: Locale; points: DailyCount[]; days: number; title: string }) {
  const t = getMessages(locale).stats;
  const series = fillDays(points, days, lastDay(points));
  const total = series.reduce((sum, point) => sum + point.count, 0);
  const width = 560;
  const height = 180;
  const left = 36;
  const bottom = 22;
  const plotW = width - left - 8;
  const plotH = height - bottom - 8;
  const ticks = niceTicks(Math.max(...series.map((point) => point.count)));
  const top = ticks[ticks.length - 1] || 1;
  const scaled = scalePoints([...series, { date: "", count: top }], plotW, plotH, 0).slice(0, series.length);
  // scalePoints 按最大值缩放 —— 塞一个等于刻度上界的点再拿掉,让线和刻度用同一把尺子。
  const shifted = scaled.map((point, index) => ({ ...point, x: left + (plotW * index) / Math.max(1, series.length - 1), y: 8 + point.y }));
  const slot = plotW / series.length;
  return (
    <figure className="m-0 grid gap-3 rounded-2xl border border-border bg-card p-5">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-semibold">{title}</span>
        <span className="text-xs text-muted-foreground">{fill(t.total, { count: formatCount(total, locale) })}</span>
      </figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" aria-label={`${title}: ${formatCount(total, locale)}`}>
        {ticks.map((tick) => {
          const y = 8 + plotH - (tick / top) * plotH;
          return (
            <g key={tick}>
              <line x1={left} x2={width - 8} y1={y} y2={y} className="stroke-border" strokeWidth={1} />
              <text x={left - 6} y={y + 3.5} textAnchor="end" className="fill-muted-foreground font-mono text-[10px]">
                {formatCount(tick, locale)}
              </text>
            </g>
          );
        })}
        <path d={areaPath(shifted, 8 + plotH)} className="fill-primary/10" />
        <path d={linePath(shifted)} className="fill-none stroke-primary" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {shifted.map((point, index) => (
          <rect key={point.date} x={left + index * slot - slot / 2} y={8} width={slot} height={plotH} className="fill-transparent hover:fill-primary/8">
            <title>{`${formatDate(point.date, locale)} · ${formatCount(point.count, locale)}`}</title>
          </rect>
        ))}
        <text x={left} y={height - 4} className="fill-muted-foreground text-[10px]">
          {formatDate(series[0].date, locale)}
        </text>
        <text x={width - 8} y={height - 4} textAnchor="end" className="fill-muted-foreground text-[10px]">
          {formatDate(series[series.length - 1].date, locale)}
        </text>
      </svg>
    </figure>
  );
}

const LEVEL_CLASS = ["fill-secondary", "fill-primary/25", "fill-primary/45", "fill-primary/70", "fill-primary"] as const;

/** 作者主页的贡献热力图:一列一周,一行一个星期几。窄屏横向滚动,不缩到看不清。 */
export function Heatmap({ locale, points }: { locale: Locale; points: DailyCount[] }) {
  const t = getMessages(locale).profile;
  const cells = heatmapCells(points, lastDay(points));
  const total = cells.reduce((sum, cell) => sum + cell.count, 0);
  const size = 11;
  const gap = 3;
  const weeks = cells[cells.length - 1].week + 1;
  const width = weeks * (size + gap);
  const height = 7 * (size + gap);
  return (
    <figure className="m-0 grid gap-3">
      <div className="overflow-x-auto pb-1">
        <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} aria-label={fill(t.contributionsSummary, { count: total })}>
          {cells.map((cell) => (
            <rect
              key={cell.date}
              x={cell.week * (size + gap)}
              y={cell.weekday * (size + gap)}
              width={size}
              height={size}
              rx={2.5}
              className={LEVEL_CLASS[cell.level]}
            >
              <title>{`${formatDate(cell.date, locale)} · ${cell.count}`}</title>
            </rect>
          ))}
        </svg>
      </div>
      <figcaption className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
        <span>{fill(t.contributionsSummary, { count: formatCount(total, locale) })}</span>
        <span className="inline-flex items-center gap-1">
          {t.less}
          <svg width={5 * (size + gap)} height={size} aria-hidden>
            {LEVEL_CLASS.map((className, index) => (
              <rect key={className} x={index * (size + gap)} width={size} height={size} rx={2.5} className={className} />
            ))}
          </svg>
          {t.more}
        </span>
      </figcaption>
    </figure>
  );
}
