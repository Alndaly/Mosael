/**
 * 播放头上的编辑落在谁身上。纯函数:不碰 React、store、API 类型,给 S / ⌘K / Q / W 这些
 * 「对着播放头下手」的快捷键共用,也让它们能拿**执行那一刻**的时间线重新算一遍(见 sequenceEditScope)。
 */
import { clipEnd, timelineToSrc, type ClipLike } from "./geometry";

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

/** ⌘K:播放头下每一条未锁定轨上的片段各切一刀。 */
export function splitPointsAcrossTracks<C extends ClipLike>(tracks: TrackLike<C>[], time: number): SplitPoint[] {
  const points: SplitPoint[] = [];
  for (const track of tracks) {
    if (track.locked) continue;
    for (const clip of track.clips ?? []) {
      if (clipContains(clip, time)) points.push({ clipId: clip.id, srcTime: timelineToSrc(clip, time) });
    }
  }
  return points;
}
