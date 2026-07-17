/** 调色风格预设(纯数据)。一键把选中片段的调色滑杆 + 曲线填成一套"看家"外观,
 *  用户随后仍可微调。作用对象是 clip.effects.color。
 *
 *  值域与滑杆一致:归一化 [-1, 1](面板显示为 value*100)。温度是反的 —— 正值更暖
 *  (后端 6500 - value*2500 → 更低色温),故"暖"用正温度、"冷"用负温度。
 *
 *  零运行时依赖,便于单测,也可复用给后续的 AI / MCP 调色工具。 */

import { IDENTITY_CURVE, type ColorCurves } from "@/features/editor/colorCurves";

export type GradeValues = Record<string, number>;

export interface ColorPreset {
  /** i18n 后缀:colorPreset_<key>。 */
  key: string;
  /** 归一化调色滑杆值。 */
  grade: GradeValues;
  /** 可选签名曲线(如电影感的 Luma S 曲线)。 */
  curves?: ColorCurves;
}

/** 电影感:抬黑 + 压高光的 filmic S 曲线,叠在滑杆推的对比之上。 */
const CINEMATIC_LUMA: ColorCurves = {
  luma: [
    [0, 0.06],
    [0.25, 0.20],
    [0.75, 0.82],
    [1, 0.95],
  ],
  r: IDENTITY_CURVE,
  g: IDENTITY_CURVE,
  b: IDENTITY_CURVE,
};

/** "无" 用空 key,不出现在此表;下方按钮单独渲染。 */
export const COLOR_PRESETS: ColorPreset[] = [
  { key: "vivid", grade: { saturation: 0.3, vibrance: 0.35, contrast: 0.12 } },
  { key: "bw", grade: { saturation: -1, contrast: 0.1 } },
  { key: "warm", grade: { temperature: 0.3, tint: 0.06, saturation: 0.08 } },
  { key: "cool", grade: { temperature: -0.28, tint: -0.05, saturation: 0.06 } },
  {
    key: "cinematic",
    grade: { contrast: 0.14, saturation: -0.06, shadows: 0.18, highlights: -0.1, temperature: -0.06, fade: 0.05 },
    curves: CINEMATIC_LUMA,
  },
  { key: "fade", grade: { fade: 0.3, contrast: -0.12, saturation: -0.2, blacks: 0.1 } },
];

/** 预设 → 写进 effects.color 的完整负载(滑杆值 + 可选曲线)。不含 filter。 */
export function presetColorPayload(preset: ColorPreset): Record<string, unknown> {
  const payload: Record<string, unknown> = { ...preset.grade };
  if (preset.curves) payload.curves = preset.curves;
  return payload;
}

const canonCurves = (c: ColorCurves | undefined): string =>
  c ? JSON.stringify((["luma", "r", "g", "b"] as const).map((ch) => c[ch]?.map(([x, y]) => [+x.toFixed(3), +y.toFixed(3)]))) : "";

/** 当前 color 精确匹配哪个预设?匹配返回其 key,否则 null(=自定义 / 无)。 */
export function matchColorPreset(color: Record<string, unknown> | undefined): string | null {
  if (!color) return null;
  const curves = color.curves as ColorCurves | undefined;
  for (const preset of COLOR_PRESETS) {
    // 预设定义的每个滑杆键都要吻合;未定义的键必须为 0(或缺省)。curves/lut 是
    // 独立图层,不参与滑杆匹配(电影预设的曲线在下方单独比对)。
    const keys = new Set([
      ...Object.keys(preset.grade),
      ...Object.keys(color).filter((k) => k !== "curves" && k !== "lut"),
    ]);
    let ok = true;
    for (const k of keys) {
      const want = preset.grade[k] ?? 0;
      const got = Number(color[k]) || 0;
      if (Math.abs(want - got) > 0.005) {
        ok = false;
        break;
      }
    }
    if (ok && canonCurves(curves) === canonCurves(preset.curves)) return preset.key;
  }
  return null;
}
