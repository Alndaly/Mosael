/** 调色曲线(纯函数域,达芬奇式 Luma/R/G/B)。移植自前身项目的 color-grade。
 *
 *  - 预览:SVG feComponentTransfer 逐通道查表近似(见 colorCurvesTables)。
 *  - 导出:后端把同样的点烧成 ffmpeg `curves=master:r:g:b`。
 *
 *  存储:clip.effects.color.curves = { luma, r, g, b: [[x,y], ...] },x/y 均 0..1,
 *  identity = [[0,0],[1,1]]。零运行时依赖,便于单测。 */

export type CurvePoint = [number, number];
export interface ColorCurves {
  luma: CurvePoint[];
  r: CurvePoint[];
  g: CurvePoint[];
  b: CurvePoint[];
}

export const IDENTITY_CURVE: CurvePoint[] = [
  [0, 0],
  [1, 1],
];
export const IDENTITY_CURVES: ColorCurves = {
  luma: IDENTITY_CURVE,
  r: IDENTITY_CURVE,
  g: IDENTITY_CURVE,
  b: IDENTITY_CURVE,
};

const isIdentityChannel = (pts: CurvePoint[] | undefined): boolean =>
  !pts || (pts.length === 2 && pts[0][0] === 0 && pts[0][1] === 0 && pts[1][0] === 1 && pts[1][1] === 1);

/** 四通道都是 identity 时可整体跳过曲线滤镜。 */
export function curvesAreIdentity(c: ColorCurves | undefined): boolean {
  if (!c) return true;
  return isIdentityChannel(c.luma) && isIdentityChannel(c.r) && isIdentityChannel(c.g) && isIdentityChannel(c.b);
}

/** 在 x∈[0,1] 处求曲线值:单调三次 Hermite(Fritsch–Carlson)。
 *  共线点(含 identity)精确还原直线、其余平滑且不过冲 —— 编辑器画的曲线、
 *  预览查表、导出近似三者共用同一条函数。 */
export function evalCurve(points: CurvePoint[], x: number): number {
  const pts = [...(points ?? IDENTITY_CURVE)].sort((a, b) => a[0] - b[0]);
  if (pts.length === 0) return x;
  if (pts.length === 1 || x <= pts[0][0]) return pts[0][1];
  const n = pts.length;
  if (x >= pts[n - 1][0]) return pts[n - 1][1];

  // 段宽 h、割线斜率 d,再按 FC 规则求各点切线 m(异号/零斜率处切线置 0 保单调)。
  const h: number[] = [];
  const d: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    const dx = pts[i + 1][0] - pts[i][0];
    h.push(dx);
    d.push(dx === 0 ? 0 : (pts[i + 1][1] - pts[i][1]) / dx);
  }
  const m: number[] = [d[0]];
  for (let i = 1; i < n - 1; i++) {
    if (d[i - 1] * d[i] <= 0) m.push(0);
    else m.push((3 * (h[i - 1] + h[i])) / ((2 * h[i] + h[i - 1]) / d[i - 1] + (h[i] + 2 * h[i - 1]) / d[i]));
  }
  m.push(d[n - 2]);

  for (let i = 0; i < n - 1; i++) {
    if (x > pts[i + 1][0]) continue;
    const t = h[i] === 0 ? 0 : (x - pts[i][0]) / h[i];
    const t2 = t * t;
    const t3 = t2 * t;
    return (
      (2 * t3 - 3 * t2 + 1) * pts[i][1] +
      (t3 - 2 * t2 + t) * h[i] * m[i] +
      (-2 * t3 + 3 * t2) * pts[i + 1][1] +
      (t3 - t2) * h[i] * m[i + 1]
    );
  }
  return pts[n - 1][1];
}

export const CURVES_FILTER_ID = "openstudio-color-curves";

/** 每通道的 feComponentTransfer tableValues,identity 时返回 null。
 *
 *  关键(用真实探测换来的知识):**先应用通道曲线,再在结果上叠主(luma)曲线** —— 即
 *  master_lut[channel_lut[x]],这正是 ffmpeg `curves=master:r:g:b` 的实际求值顺序。
 *  按文档字面的"先 luma"去写,当 luma 与某通道曲线同时非 identity 时,预览会与导出明显不一致。 */
export function colorCurvesTables(
  curves: ColorCurves | undefined,
): { r: string; g: string; b: string } | null {
  if (curvesAreIdentity(curves)) return null;
  const c = curves!;
  const N = 32;
  const sample = (channel: CurvePoint[]) => {
    const out: string[] = [];
    for (let i = 0; i <= N; i++) {
      const x = i / N;
      out.push(Math.max(0, Math.min(1, evalCurve(c.luma, evalCurve(channel, x)))).toFixed(4));
    }
    return out.join(" ");
  };
  return { r: sample(c.r), g: sample(c.g), b: sample(c.b) };
}
