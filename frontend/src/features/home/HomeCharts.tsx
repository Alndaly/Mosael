import React from "react";

import type { WorkspaceSummary } from "@/api/client";
import { useI18n } from "@/app/preferences";

/**
 * 首页图表:近 14 天任务活动(堆叠柱)+ 素材构成(分段条)。
 *
 * 手写 SVG 而非引入图表库:两张小图,规格(细柱、数据端 4px 圆角、段间 2px 留白、
 * 退隐网格、悬停提示)手写反而更贴设计系统。颜色走 tokens.css 的 --chart-*
 * (dataviz 校验通过的明暗两档);文本一律用文本色,不穿系列色。
 */

const PLOT_H = 96;
const BAR_MAX_W = 14;
const GAP = 2; // 堆叠段之间的表面留白

/** 顶部圆角的柱段(数据端圆角、基线端直角——rect 的 rx 会把四角都圆掉)。 */
function roundedTopBar(x: number, y: number, w: number, h: number, r: number): string {
  const radius = Math.min(r, w / 2, h);
  return [
    `M ${x} ${y + h}`,
    `V ${y + radius}`,
    `Q ${x} ${y} ${x + radius} ${y}`,
    `H ${x + w - radius}`,
    `Q ${x + w} ${y} ${x + w} ${y + radius}`,
    `V ${y + h}`,
    "Z",
  ].join(" ");
}

export function ActivityChart({ daily }: { daily: WorkspaceSummary["daily"] }) {
  const t = useI18n();
  const max = Math.max(...daily.map((day) => day.succeeded + day.failed));
  if (max === 0) {
    return <p className="home-chart-empty">{t("homeChartEmptyActivity")}</p>;
  }
  const width = 100; // viewBox 百分比坐标,横向自适应
  const slot = width / daily.length;
  const barW = Math.min(BAR_MAX_W, slot * 0.55);

  return (
    <>
      <svg
        className="home-chart-plot"
        viewBox={`0 0 ${width} ${PLOT_H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={t("homeChartActivity")}
      >
        {/* 退隐基线 */}
        <line x1="0" y1={PLOT_H - 0.5} x2={width} y2={PLOT_H - 0.5} className="home-chart-baseline" />
        {daily.map((day, index) => {
          const total = day.succeeded + day.failed;
          if (total === 0) return null;
          const x = index * slot + (slot - barW) / 2;
          const okH = (day.succeeded / max) * PLOT_H;
          const failH = (day.failed / max) * PLOT_H;
          const failY = PLOT_H - okH - (day.succeeded > 0 && day.failed > 0 ? GAP : 0) - failH;
          const label = `${day.date.slice(5)} · ${t("homeLegendSucceeded")} ${day.succeeded} · ${t("homeLegendFailed")} ${day.failed}`;
          return (
            <g key={day.date}>
              <title>{label}</title>
              {/* 命中区比柱宽,悬停不用瞄准 */}
              <rect x={index * slot} y="0" width={slot} height={PLOT_H} fill="transparent" />
              {day.succeeded > 0 &&
                (day.failed > 0 ? (
                  <rect x={x} y={PLOT_H - okH} width={barW} height={okH} className="home-chart-ok" />
                ) : (
                  <path d={roundedTopBar(x, PLOT_H - okH, barW, okH, 2)} className="home-chart-ok" />
                ))}
              {day.failed > 0 && <path d={roundedTopBar(x, failY, barW, failH, 2)} className="home-chart-fail" />}
            </g>
          );
        })}
      </svg>
      {/* 稀疏日期刻度(首/中/尾)放 HTML 行:SVG 被 preserveAspectRatio=none
          横向拉伸,文字放里面会跟着变形 */}
      <div className="home-chart-ticks">
        {[0, Math.floor(daily.length / 2), daily.length - 1].map((index) => (
          <span key={index}>{daily[index].date.slice(5)}</span>
        ))}
      </div>
      <div className="home-chart-legend">
        <span>
          <i className="home-chart-dot" style={{ background: "var(--chart-ok)" }} /> {t("homeLegendSucceeded")}
        </span>
        <span>
          <i className="home-chart-dot" style={{ background: "var(--chart-fail)" }} /> {t("homeLegendFailed")}
        </span>
        <span className="home-chart-max">max {max}</span>
      </div>
    </>
  );
}

const KIND_ORDER = [
  { kind: "video", token: "var(--chart-video)", label: "homeKindVideo" },
  { kind: "audio", token: "var(--chart-audio)", label: "homeKindAudio" },
  { kind: "image", token: "var(--chart-image)", label: "homeKindImage" },
] as const;

export function AssetKindsChart({ assetKinds }: { assetKinds: WorkspaceSummary["asset_kinds"] }) {
  const t = useI18n();
  const known = KIND_ORDER.map((entry) => ({ ...entry, count: assetKinds[entry.kind] ?? 0 }));
  const other = Object.entries(assetKinds)
    .filter(([kind]) => !KIND_ORDER.some((entry) => entry.kind === kind))
    .reduce((sum, [, count]) => sum + count, 0);
  const total = known.reduce((sum, entry) => sum + entry.count, 0) + other;
  if (total === 0) {
    return <p className="home-chart-empty">{t("homeChartEmptyAssets")}</p>;
  }
  const segments = [
    ...known.filter((entry) => entry.count > 0).map((entry) => ({ ...entry, name: t(entry.label) })),
    ...(other > 0 ? [{ kind: "other", token: "var(--muted-foreground)", name: t("homeKindOther"), count: other }] : []),
  ];

  return (
    <>
      <div className="home-chart-bar" role="img" aria-label={t("homeChartAssets")}>
        {segments.map((segment) => (
          <span
            key={segment.kind}
            className="home-chart-seg"
            style={{ flexGrow: segment.count, background: segment.token }}
            title={`${segment.name} ${segment.count}`}
          />
        ))}
      </div>
      {/* 直接标注计数:分段条对比度告警的救济,也免去悬停才能读数 */}
      <div className="home-chart-legend">
        {segments.map((segment) => (
          <span key={segment.kind}>
            <i className="home-chart-dot" style={{ background: segment.token }} /> {segment.name}{" "}
            <em className="home-chart-count">{segment.count}</em>
          </span>
        ))}
      </div>
    </>
  );
}
