import { sampleCamera, sampleObject } from "./sceneGraph";
import type { Keyframe, SceneContent, SceneObject, SceneShot } from "@/api/domains/scenes";

/**
 * 关键帧:**谁在第几秒是什么样**。
 *
 * 这一份是纯逻辑,从 SceneStudio / SceneInspector / SceneCameraPanel 三处抽出来的 ——
 * 「在当前时刻记一档」此前在这三个地方各写了一遍,而它们对同一件事的答案已经开始不一样了
 * (相机那份会补 0 秒的静止姿态,物体那份也会,但上限判断一个是 `>= 100` 一个是 `> 100`)。
 * 现在快捷键 `I` 是第四个调用方 —— 再抄一遍必然继续漂。
 */

/** 一条轨最多几档。后端的 `Keyframe` 列表上限也是这个数,超了会被拒。 */
export const MAX_KEYS = 100;

/** 认为"这两个时刻是同一档"的容差。滑块步长 0.01,所以 1 毫秒足够分得开。 */
const EPSILON = 0.001;

/** 这一刻在轨上的下标;不在任何一档上就是 -1。 */
export function keyIndexAt(track: Keyframe[], time: number): number {
  return track.findIndex((frame) => Math.abs(frame.time - time) < EPSILON);
}

/**
 * 物体此刻的**静止姿态**,写成一档关键帧的形状。
 *
 * 相机和别的物体记的字段不同:相机记「在哪儿、看哪儿、多广」,别的物体记「在哪儿、转多少、
 * 多大」。同一个 Keyframe 结构装得下两者(除 time/position 外都是可选的),但**不能混着记**
 * —— 给相机记一个 scale,采样时没人读它;给方块记一个 target 同理。
 */
export function stillFrame(object: SceneObject, time = 0): Keyframe {
  return object.kind === "camera"
    ? { time, position: object.position, target: object.target, fov: object.fov }
    : { time, position: object.position, rotation: object.rotation, scale: object.scale };
}

/** 只插入指定时刻；单帧同样是有效动画数据，不能自动补帧或连带删除。 */
export function upsertKey(track: Keyframe[], frame: Keyframe): Keyframe[] | null {
  const kept = track.filter(one => Math.abs(one.time - frame.time) >= EPSILON);
  if (kept.length >= MAX_KEYS) return null;
  return [...kept, frame].sort((a, b) => a.time - b.time);
}

export function removeKeyAt(track: Keyframe[], time: number): Keyframe[] | null {
  const index = keyIndexAt(track, time);
  return index < 0 ? null : track.filter((_, i) => i !== index);
}

/** 打帧记录此刻的采样值；只有手动调整过的物体使用尚未打帧的姿态。 */
export function frameForObject(object: SceneObject, shot: SceneShot, time: number, posing: boolean): Keyframe {
  if (posing) return stillFrame(object, time);
  return object.kind === "camera"
    ? sampleCamera(object, shot, time)
    : { time, ...sampleObject(object, shot, time) };
}

export type SceneKey = { id: string; time: number };
export function sameKey(a: SceneKey, b: SceneKey) {
  return a.id === b.id && Math.abs(a.time - b.time) < EPSILON;
}

/** 批量平移是一次原子操作，碰撞或越界时不覆盖任何已有帧。 */
export function moveSceneKeys(content: SceneContent, keys: SceneKey[], delta: number, end: number): SceneContent | null {
  if (!Number.isFinite(delta)) return null;
  let invalid = false;
  const objects = content.objects.map(object => {
    const track = object.track.map(frame => {
      if (!keys.some(key => sameKey(key, {id: object.id, time: frame.time}))) return frame;
      const time = Number((frame.time + delta).toFixed(6));
      if (time < 0 || time > end) invalid = true;
      return {...frame, time};
    }).sort((a, b) => a.time - b.time);
    if (track.some((frame, i) => i > 0 && frame.time - track[i - 1].time < EPSILON)) invalid = true;
    return {...object, track};
  });
  return invalid ? null : {...content, objects};
}

/** 往前 / 往后最近的那一档的时刻。没有就返回 null(到头了,不循环)。 */
export function neighbourKeyTime(times: number[], time: number, direction: 1 | -1): number | null {
  const sorted = [...times].sort((a, b) => a - b);
  const found =
    direction > 0
      ? sorted.find((one) => one > time + EPSILON)
      : [...sorted].reverse().find((one) => one < time - EPSILON);
  return found ?? null;
}

/** 摊平成关键帧视图的一行。 */
export interface TrackRow {
  object: SceneObject;
  /** 这一行上的时刻。空数组 = 这个物体不动(行仍然在,那是"可以在这儿记一档"的位置)。 */
  times: number[];
  /** 拍当前镜头的那台机位。它排在最上,而且永远有一行。 */
  isRig: boolean;
}

/** 默认完整列出场景物体，筛选由界面显式控制，不能随选择改变。 */
export function trackRows(content: SceneContent, shot: SceneShot): TrackRow[] {
  const rows = content.objects.map(object => ({
    object, times: object.track.map(frame => frame.time), isRig: object.id === shot.camera_id,
  }));
  return [...rows.filter(row => row.isRig), ...rows.filter(row => !row.isRig)];
}
