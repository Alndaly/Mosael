import { colorCurvesTables, type ColorCurves } from "@/features/editor/colorCurves";

/** CSS approximations of the backend FFmpeg filter presets (render_plan.FILTER_PRESETS). */
export const FILTER_CSS: Record<string, string> = {
  bw: "grayscale(1)",
  warm: "sepia(0.22) saturate(1.15)",
  cool: "hue-rotate(-8deg) saturate(1.1) brightness(1.02)",
  vivid: "saturate(1.4) contrast(1.06)",
  fade: "saturate(0.75) contrast(0.9) brightness(1.05)",
};

export type ClipEffects = {
  filter?: string;
  color?: Record<string, number> & { curves?: ColorCurves };
};

/** Pure CSS approximation of a clip's grade/preset — shared by every canvas element so each
 *  clip filters independently. Curve tables come back separately (need an SVG feComponentTransfer). */
export function computeFilters(effects: ClipEffects): {
  cssFilter: string;
  vignette: number;
  curveTables: { r: string; g: string; b: string } | null;
} {
  const parts: string[] = [];
  const preset = FILTER_CSS[String(effects.filter ?? "")];
  if (preset) parts.push(preset);
  const grade = effects.color ?? {};
  const v = (key: string) => Math.max(-1, Math.min(1, Number(grade[key]) || 0));
  const brightFactor = (1 + v("brightness")) * (1 + v("exposure") / 2);
  if (Math.abs(brightFactor - 1) > 0.005) parts.push(`brightness(${brightFactor.toFixed(3)})`);
  if (v("contrast")) parts.push(`contrast(${(1 + v("contrast") * 0.6).toFixed(3)})`);
  if (v("gamma")) parts.push(`brightness(${(1 + v("gamma") * 0.25).toFixed(3)})`);
  const sat = 1 + v("saturation") + v("vibrance") * 0.5;
  if (Math.abs(sat - 1) > 0.005) parts.push(`saturate(${Math.max(0, sat).toFixed(3)})`);
  if (v("hue")) parts.push(`hue-rotate(${(v("hue") * 180).toFixed(1)}deg)`);
  const w = v("temperature");
  if (w > 0) parts.push(`sepia(${(w * 0.25).toFixed(3)})`);
  else if (w < 0) parts.push(`hue-rotate(${(w * 12).toFixed(1)}deg) saturate(${(1 - w * 0.08).toFixed(3)})`);
  if (v("tint")) parts.push(`hue-rotate(${(v("tint") * -8).toFixed(1)}deg)`);
  const fadeAmount = Math.max(0, v("fade"));
  if (fadeAmount) parts.push(`contrast(${(1 - fadeAmount * 0.25).toFixed(3)}) brightness(${(1 + fadeAmount * 0.08).toFixed(3)})`);
  const tables = colorCurvesTables(grade.curves);
  return { cssFilter: parts.join(" "), vignette: Math.max(0, v("vignette")), curveTables: tables };
}
