/**
 * 播放头上的编辑落在谁身上。纯函数:不碰 React、store、API 类型,给 S / ⌘K / Q / W 这些
 * 「对着播放头下手」的快捷键共用,也让它们能拿**执行那一刻**的时间线重新算一遍(见 sequenceEditScope)。
 */
import { clipEnd, timelineToSrc, type ClipLike } from "./geometry";

/** 片段可能属于一个链接组(视频和从它分离出去的音频):组员一起切、一起动。 */
export type LinkableClip = ClipLike & { link_group?: string | null };

export interface TrackLike<C extends ClipLike = ClipLike> {
  id: string;
  locked?: boolean;
  clips?: C[];
}

/** 片段严格包住这一刻(不含两端):切在边缘上切不出东西。 */
export function clipContains(clip: ClipLike, time: number): boolean {
  return time > clip.timeline_start + 1e-9 && time < clipEnd(clip) - 1e-9;
}

export interface SplitPoint {
  clipId: string;
  srcTime: number;
}

/**
 * 在 time 处切一刀,切谁:给了 trackId 就只看那条轨(选中片段所在的轨 —— 它可能已经被前一刀
 * 切开,片段 id 换了,但轨道还是那条);没给就是播放头下的第一段。锁定的轨不动。
 */
export function splitPointAt<C extends ClipLike>(
  tracks: TrackLike<C>[],
  time: number,
  trackId: string | null = null,
): SplitPoint | null {
  for (const track of tracks) {
    if (track.locked) continue;
    if (trackId !== null && track.id !== trackId) continue;
    const clip = (track.clips ?? []).find((item) => clipContains(item, time));
    if (clip) return { clipId: clip.id, srcTime: timelineToSrc(clip, time) };
  }
  return null;
}

/**
 * ⇧⌘K:播放头下每一条未锁定轨上的片段各切一刀。
 *
 * 链接组只报一段:切开它时后端会在同一时刻切开它的组员,并把左右两截各自配好对(左半跟左半);
 * 组员再单独切一次就切了两遍 —— 而且它在第一刀里已经被换成两截,原 id 找不到了。
 */
export function splitPointsAcrossTracks<C extends LinkableClip>(tracks: TrackLike<C>[], time: number): SplitPoint[] {
  const points: SplitPoint[] = [];
  const groups = new Set<string>();
  for (const track of tracks) {
    if (track.locked) continue;
    for (const clip of track.clips ?? []) {
      if (!clipContains(clip, time)) continue;
      if (clip.link_group) {
        if (groups.has(clip.link_group)) continue;
        groups.add(clip.link_group);
      }
      points.push({ clipId: clip.id, srcTime: timelineToSrc(clip, time) });
    }
  }
  return points;
}

/** 编辑点:时间线开头 + 每条轨上每段片段的头和尾(去重、升序)。↑ / ↓ 在它们之间跳。 */
export function editPoints<C extends ClipLike>(tracks: TrackLike<C>[]): number[] {
  const points = new Set<number>([0]);
  for (const track of tracks) {
    for (const clip of track.clips ?? []) {
      points.add(clip.timeline_start);
      points.add(clipEnd(clip));
    }
  }
  return [...points].sort((a, b) => a - b);
}

/**
 * 从 time 往前(-1)/ 往后(1)最近的编辑点。正停在某一点上(误差 tolerance 以内,通常取半帧)
 * 时跳过它,否则按一下原地不动。没有了返回 null。
 */
export function adjacentEditPoint(points: number[], time: number, direction: -1 | 1, tolerance = 1e-6): number | null {
  if (direction > 0) return points.find((point) => point > time + tolerance) ?? null;
  for (let index = points.length - 1; index >= 0; index -= 1) {
    if (points[index] < time - tolerance) return points[index];
  }
  return null;
}

export interface RippleTrimPlan {
  /** 剪掉的时间线区间 [from, to)。Q 之后播放头落到 from。 */
  from: number;
  to: number;
  cuts: Array<{ clipId: string; srcStart: number; srcEnd: number }>;
}

/**
 * Q / W 波纹修剪到播放头(Premiere 的「波纹修剪上一个 / 下一个编辑点到播放头」)。
 *
 * 目标轨:选中的片段里有压在播放头上的,就是它们所在的轨;否则是播放头下有片段的每一条未锁定轨。
 * 剪掉的区间对**所有目标轨一样长** —— Q 是「目标轨上播放头之前最近的编辑点 → 播放头」,W 是
 * 「播放头 → 之后最近的编辑点」—— 各轨按各自的片段剪,剪完一起左移同样的长度,彼此保持同步。
 * 每条目标轨上压着播放头的那一段一定包住整个区间(它自己的头尾也在编辑点里),所以一轨一刀。
 */
export function rippleTrimCuts<C extends ClipLike>(
  tracks: TrackLike<C>[],
  time: number,
  edge: "start" | "end",
  selectedClipIds: string[],
): RippleTrimPlan | null {
  const underPlayhead = tracks
    .filter((track) => !track.locked)
    .map((track) => ({ track, clip: (track.clips ?? []).find((item) => clipContains(item, time)) }))
    .filter((entry): entry is { track: TrackLike<C>; clip: C } => Boolean(entry.clip));
  const selected = underPlayhead.filter((entry) => selectedClipIds.includes(entry.clip.id));
  const targets = selected.length > 0 ? selected : underPlayhead;
  if (targets.length === 0) return null;
  const points = editPoints(targets.map((entry) => entry.track));
  const bound = adjacentEditPoint(points, time, edge === "start" ? -1 : 1);
  if (bound === null) return null;
  const [from, to] = edge === "start" ? [bound, time] : [time, bound];
  return {
    from,
    to,
    cuts: targets.map(({ clip }) => ({
      clipId: clip.id,
      srcStart: timelineToSrc(clip, from),
      srcEnd: timelineToSrc(clip, to),
    })),
  };
}

/**
 * ⌥ + 方向键移动选中:左右是同一轨上按时间顺序的前一段 / 后一段;上下是相邻那条有片段的轨上
 * 时间上最接近的一段(包住当前片段起点的优先,空轨跳过)。没有当前选中时从第一条轨的第一段开始。
 * tracks 按界面上的顺序(从上到下)传入。到头了返回 null。
 */
export function adjacentClip<C extends ClipLike>(
  tracks: TrackLike<C>[],
  currentId: string | null,
  direction: "left" | "right" | "up" | "down",
): string | null {
  const lanes = tracks.map((track) => [...(track.clips ?? [])].sort((a, b) => a.timeline_start - b.timeline_start));
  const laneIndex = lanes.findIndex((lane) => lane.some((item) => item.id === currentId));
  if (laneIndex < 0) return lanes.find((lane) => lane.length > 0)?.[0]?.id ?? null;
  const lane = lanes[laneIndex];
  const index = lane.findIndex((item) => item.id === currentId);
  const current = lane[index];
  if (direction === "left" || direction === "right") return lane[index + (direction === "left" ? -1 : 1)]?.id ?? null;
  const step = direction === "up" ? -1 : 1;
  for (let other = laneIndex + step; other >= 0 && other < lanes.length; other += step) {
    const candidates = lanes[other];
    if (candidates.length === 0) continue;
    const at = current.timeline_start;
    const covering = candidates.find((item) => item.timeline_start <= at && at < clipEnd(item));
    if (covering) return covering.id;
    return candidates.reduce((best, item) =>
      Math.abs(item.timeline_start - at) < Math.abs(best.timeline_start - at) ? item : best,
    ).id;
  }
  return null;
}
