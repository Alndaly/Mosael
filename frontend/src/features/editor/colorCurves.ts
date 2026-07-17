/** 调色曲线(纯函数域,达芬奇式 Luma/R/G/B)。移植自 mibu-video 的 color-grade。
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

/** 在 x∈[0,1] 处求曲线值(排序后控制点间线性插值)。 */
export function evalCurve(points: CurvePoint[], x: number): number {
  const pts = [...(points ?? IDENTITY_CURVE)].sort((a, b) => a[0] - b[0]);
  if (pts.length === 0) return x;
  if (x <= pts[0][0]) return pts[0][1];
  for (let i = 1; i < pts.length; i++) {
    if (x <= pts[i][0]) {
      const [x0, y0] = pts[i - 1];
      const [x1, y1] = pts[i];
      const t = x1 === x0 ? 0 : (x - x0) / (x1 - x0);
      return y0 + (y1 - y0) * t;
    }
  }
  return pts[pts.length - 1][1];
}

export const CURVES_FILTER_ID = "mibu-color-curves";

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
