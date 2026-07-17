import React from "react";

import { useI18n } from "@/app/preferences";
import {
  IDENTITY_CURVE,
  IDENTITY_CURVES,
  evalCurve,
  type ColorCurves,
  type CurvePoint,
} from "@/features/editor/colorCurves";

type Channel = "luma" | "r" | "g" | "b";
const CHANNELS: { key: Channel; label: string; stroke: string }[] = [
  { key: "luma", label: "Luma", stroke: "var(--foreground)" },
  { key: "r", label: "R", stroke: "#e5484d" },
  { key: "g", label: "G", stroke: "#30a46c" },
  { key: "b", label: "B", stroke: "#3e63dd" },
];

const clamp01 = (n: number) => Math.max(0, Math.min(1, n));

/** 达芬奇式色调曲线编辑器:通道分页 + 拖点 + 空白处加点 + 双击删点。作用于选中片段的 curves。 */
export function CurveEditor({
  curves,
  onChange,
  onCommitStart,
}: {
  curves: ColorCurves | undefined;
  onChange: (next: ColorCurves) => void;
  /** 拖动/加点/删点开始前调用一次(供调色撤销栈记快照)。 */
  onCommitStart?: () => void;
}) {
  const t = useI18n();
  const [channel, setChannel] = React.useState<Channel>("luma");
  const svgRef = React.useRef<SVGSVGElement | null>(null);
  const dragIndex = React.useRef<number | null>(null);

  const base = curves ?? IDENTITY_CURVES;
  const points = base[channel] ?? IDENTITY_CURVE;

  const setPoints = (next: CurvePoint[]) => {
    const sorted = [...next].sort((a, b) => a[0] - b[0]);
    onChange({ ...base, [channel]: sorted });
  };

  const toNorm = (event: React.PointerEvent | PointerEvent): CurvePoint => {
    const rect = svgRef.current!.getBoundingClientRect();
    const x = clamp01((event.clientX - rect.left) / rect.width);
    const y = clamp01(1 - (event.clientY - rect.top) / rect.height); // y inverted for display
    return [x, y];
  };

  const nearestPointIndex = (nx: number, ny: number): number | null => {
    let best = -1;
    let bestDist = 0.05 * 0.05; // ~0.05 hit radius in normalized space
    points.forEach(([px, py], i) => {
      const d = (px - nx) ** 2 + (py - ny) ** 2;
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    });
    return best >= 0 ? best : null;
  };

  const onPointerDown = (event: React.PointerEvent) => {
    const [nx, ny] = toNorm(event);
    let index = nearestPointIndex(nx, ny);
    onCommitStart?.();
    if (index === null) {
      // 空白处:插入新点,随即拖它。
      const next = [...points, [nx, ny] as CurvePoint].sort((a, b) => a[0] - b[0]);
      index = next.findIndex((p) => p[0] === nx && p[1] === ny);
      setPoints(next);
    }
    dragIndex.current = index;
    (event.target as Element).setPointerCapture?.(event.pointerId);
  };

  const onPointerMove = (event: React.PointerEvent) => {
    if (dragIndex.current === null) return;
    const i = dragIndex.current;
    const [nx, ny] = toNorm(event);
    const isEndpoint = i === 0 || i === points.length - 1;
    // 端点只能上下移(x 锁 0 / 1);内部点 x 夹在左右邻点之间。
    const next = points.map((p, idx) => {
      if (idx !== i) return p;
      if (isEndpoint) return [p[0], ny] as CurvePoint;
      const lo = points[idx - 1][0] + 0.01;
      const hi = points[idx + 1][0] - 0.01;
      return [Math.max(lo, Math.min(hi, nx)), ny] as CurvePoint;
    });
    onChange({ ...base, [channel]: next }); // 不排序(拖动中位序不变),松手时才归位
  };

  const onPointerUp = () => {
    if (dragIndex.current !== null) setPoints(points);
    dragIndex.current = null;
  };

  const removePoint = (i: number) => {
    if (i === 0 || i === points.length - 1) return; // 端点不可删
    onCommitStart?.();
    setPoints(points.filter((_, idx) => idx !== i));
  };

  const resetChannel = () => {
    onCommitStart?.();
    onChange({ ...base, [channel]: [...IDENTITY_CURVE] });
  };

  // 采样描出曲线路径(与预览/导出一致的分段线性)。
  const linePath = React.useMemo(() => {
    const N = 48;
    const pts: string[] = [];
    for (let i = 0; i <= N; i++) {
      const x = i / N;
      const y = evalCurve(points, x);
      pts.push(`${(x * 100).toFixed(2)},${((1 - y) * 100).toFixed(2)}`);
    }
    return "M" + pts.join(" L");
  }, [points]);

  const active = CHANNELS.find((c) => c.key === channel)!;

  return (
    <div className="curve-editor">
      <div className="curve-tabs">
        {CHANNELS.map((c) => (
          <button
            key={c.key}
            type="button"
            className={channel === c.key ? "curve-tab active" : "curve-tab"}
            style={channel === c.key ? { color: c.stroke, borderColor: c.stroke } : undefined}
            onClick={() => setChannel(c.key)}
          >
            {c.label}
          </button>
        ))}
        <button type="button" className="curve-reset" onClick={resetChannel} title={t("curveResetChannel")}>
          {t("gradeReset")}
        </button>
      </div>
      <svg
        ref={svgRef}
        className="curve-plot"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
      >
        {/* 网格 + identity 参考对角线 */}
        {[25, 50, 75].map((v) => (
          <React.Fragment key={v}>
            <line x1={v} y1={0} x2={v} y2={100} className="curve-grid" />
            <line x1={0} y1={v} x2={100} y2={v} className="curve-grid" />
          </React.Fragment>
        ))}
        <line x1={0} y1={100} x2={100} y2={0} className="curve-diagonal" />
        <path d={linePath} className="curve-line" style={{ stroke: active.stroke }} />
        {points.map(([px, py], i) => (
          <circle
            key={i}
            cx={px * 100}
            cy={(1 - py) * 100}
            r={2.6}
            className="curve-point"
            style={{ fill: active.stroke }}
            onDoubleClick={(event) => {
              event.stopPropagation();
              removePoint(i);
            }}
          />
        ))}
      </svg>
      <p className="curve-hint">{t("curveHint")}</p>
    </div>
  );
}
