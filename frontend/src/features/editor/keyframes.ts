import type { Clip } from "@/api/client";
import type { Transform } from "@/features/editor/TransformOverlay";

/**
 * 关键帧动画:让 clip 的 transform(位置/缩放/透明度)随时间插值,而不是全程一个静态值。
 * 这是从"能剪"到"能做花活"(推拉摇移、渐显、Ken Burns)的分水岭。
 *
 * 时间用 clip 内归一化进度 t ∈ [0,1](0=片段头,1=片段尾),而非绝对秒——这样片段被裁剪/
 * 变速/移动后动画依然贴合,不必回改每个关键帧。每个属性独立成轨:一个关键帧只需携带它要
 * 打点的属性,缺的属性从静态基值取,所以"只给 opacity 打两个点做淡入"不必同时写死 x/y/scale。
 *
 * 插值内核是纯函数,前端预览(Monitor)与后端导出(ffmpeg 表达式编译)锁步同一语义,
 * 保证所见即所得。
 */

export type KfProp = "scale" | "x" | "y" | "opacity" | "rotation";
export type Keyframe = { t: number } & Partial<Record<KfProp, number>>;

const PROPS: KfProp[] = ["scale", "x", "y", "opacity", "rotation"];

/** 某属性在 progress 处的值:只在定义了该属性的关键帧间线性插值,端点外保持端点值(hold)。 */
export function sampleProp(keyframes: Keyframe[], prop: KfProp, base: number, progress: number): number {
  const pts: Array<[number, number]> = [];
  for (const kf of keyframes) {
    const v = kf[prop];
    if (typeof v === "number") pts.push([kf.t, v]);
  }
  if (pts.length === 0) return base;
  pts.sort((a, b) => a[0] - b[0]);
  if (pts.length === 1) return pts[0][1];
  if (progress <= pts[0][0]) return pts[0][1];
  if (progress >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
  for (let i = 0; i < pts.length - 1; i++) {
    const [t0, v0] = pts[i];
    const [t1, v1] = pts[i + 1];
    if (progress >= t0 && progress <= t1) {
      const span = t1 - t0;
      const f = span > 1e-9 ? (progress - t0) / span : 0;
      return v0 + (v1 - v0) * f;
    }
  }
  return base;
}

/** 关键帧激活的条件:至少两个点,且它们在某个属性上取值不同(单点或全同 = 无动画)。 */
export function hasActiveKeyframes(tf: Transform): boolean {
  const kfs = tf.keyframes;
  if (!kfs || kfs.length < 2) return false;
  return PROPS.some((prop) => {
    const vals = kfs.filter((k) => typeof k[prop] === "number").map((k) => k[prop] as number);
    return vals.length >= 2 && new Set(vals.map((v) => v.toFixed(4))).size > 1;
  });
}

/** 静态 transform + 关键帧轨 → 在 clip 进度 progress(0..1)处的插值 transform。 */
export function sampleTransform(tf: Transform, progress: number): Transform {
  if (!hasActiveKeyframes(tf)) return tf;
  const kfs = tf.keyframes as Keyframe[];
  return {
    ...tf,
    scale: sampleProp(kfs, "scale", tf.scale, progress),
    x: sampleProp(kfs, "x", tf.x, progress),
    y: sampleProp(kfs, "y", tf.y, progress),
    opacity: sampleProp(kfs, "opacity", tf.opacity, progress),
    rotation: sampleProp(kfs, "rotation", tf.rotation, progress),
  };
}

/** playhead(时间线秒)在某 clip 内的归一化进度 0..1,考虑变速。 */
export function clipProgress(clip: Pick<Clip, "timeline_start" | "src_in" | "src_out" | "speed">, playhead: number): number {
  const speed = clip.speed || 1;
  const duration = (clip.src_out - clip.src_in) / speed;
  if (duration <= 1e-9) return 0;
  return Math.max(0, Math.min(1, (playhead - clip.timeline_start) / duration));
}

const EPS = 0.02;

/** 在给定进度处写入/更新关键帧属性(合并同 t 的点),返回排序后的新轨。 */
export function upsertKeyframe(keyframes: Keyframe[] | undefined, t: number, patch: Partial<Record<KfProp, number>>): Keyframe[] {
  const snapped = Math.max(0, Math.min(1, t));
  const rest = (keyframes ?? []).filter((k) => Math.abs(k.t - snapped) > 1e-3);
  const existing = (keyframes ?? []).find((k) => Math.abs(k.t - snapped) <= 1e-3);
  return [...rest, { ...(existing ?? {}), t: snapped, ...patch }].sort((a, b) => a.t - b.t);
}

/** 某属性的关键帧时间点(升序)。每个属性一条独立轨,这是它自己的点。 */
export function propTimes(keyframes: Keyframe[] | undefined, prop: KfProp): number[] {
  return (keyframes ?? []).filter((k) => typeof k[prop] === "number").map((k) => k.t).sort((a, b) => a - b);
}

/** 某属性在进度 t 附近是否已有关键帧。 */
export function hasPropAt(keyframes: Keyframe[] | undefined, prop: KfProp, t: number, eps = EPS): boolean {
  return (keyframes ?? []).some((k) => typeof k[prop] === "number" && Math.abs(k.t - t) <= eps);
}

/** 删除某属性在进度 t 附近的关键帧点(只删该属性;若该点因此空了,整点移除)。 */
export function removePropKeyframe(keyframes: Keyframe[] | undefined, prop: KfProp, t: number, eps = EPS): Keyframe[] {
  return (keyframes ?? [])
    .map((k) => {
      if (Math.abs(k.t - t) > eps) return k;
      const { [prop]: _drop, ...rest } = k;
      return rest as Keyframe;
    })
    .filter((k) => Object.keys(k).some((key) => key !== "t")); // 只剩时间戳 → 删点
}

/** toggle:该属性在进度 t 有点则删,无则以 value 打点。返回新轨。 */
export function togglePropKeyframe(keyframes: Keyframe[] | undefined, prop: KfProp, t: number, value: number): Keyframe[] {
  const snapped = Math.max(0, Math.min(1, t));
  return hasPropAt(keyframes, prop, snapped)
    ? removePropKeyframe(keyframes, prop, snapped)
    : upsertKeyframe(keyframes, snapped, { [prop]: value });
}
