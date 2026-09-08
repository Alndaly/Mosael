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

/**
 * 在 `frame.time` 处写入一档。返回新的轨;超过上限返回 null(调用方负责说话)。
 *
 * **轨为空时会连同静止姿态一起记成 0 秒那一档。** 否则从物体的静止位置到你刚记的这一档之间
 * 没有任何东西描述它 —— 播放时会突然跳过去,而用户只记一档的本意是"从现在这样,变成那样"。
 * (在 0 秒记第一档时不需要:那一档本身就是起点。)
 */
export function upsertKey(track: Keyframe[], still: Keyframe, frame: Keyframe): Keyframe[] | null {
  const base = track.length ? track : frame.time > EPSILON ? [still] : [];
  const kept = base.filter((one) => Math.abs(one.time - frame.time) > EPSILON);
  if (kept.length >= MAX_KEYS) return null;
  return [...kept, frame].sort((a, b) => a.time - b.time);
}

/**
 * 移除这一刻那一档。这一刻没有档就返回 null —— 调用方据此知道"没什么可删的"。
 *
 * 删到只剩一档时**整条轨清空**:一条只有一档的轨和没有轨渲染出来一模一样(处处是同一个
 * 姿态),但界面上它是"有动画"的 —— 于是用户看着一个说自己在动、实际不动的物体。
 */
export function removeKeyAt(track: Keyframe[], time: number): Keyframe[] | null {
  const index = keyIndexAt(track, time);
  if (index < 0) return null;
  const next = track.filter((_, i) => i !== index);
  return next.length <= 1 ? [] : next;
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

/**
 * 关键帧视图有哪几行。
 *
 * **只列有话可说的物体**:在动的、当前选中的、以及拍这个镜头的机位。一个二十个方块的场景
 * 全列出来的话,十九行是空的 —— 而空行不表达任何东西,只是把真正在动的那一行推出视野。
 *
 * 机位排在最上:这个镜头讲的就是它怎么走,别的物体是在它面前动。相机是场景里的物体
 * (见 docs/design/scene-time-and-cameras.md),所以它和别的物体同列一张表,只是排在第一行。
 */
export function trackRows(
  content: SceneContent,
  shot: SceneShot,
  selectedId: string | null,
): TrackRow[] {
  const rows = content.objects
    .filter((o) => o.track.length > 0 || o.id === shot.camera_id || o.id === selectedId)
    .map((object) => ({
      object,
      times: object.track.map((frame) => frame.time),
      isRig: object.id === shot.camera_id,
    }));
  return [...rows.filter((row) => row.isRig), ...rows.filter((row) => !row.isRig)];
}
