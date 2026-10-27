import type { Clip, Sequence } from "@/api/client";

/** 时间线上所有片段的扁平列表;null 序列就是空。 */
export function clipsOf(sequence: Sequence | null): Clip[] {
  return (sequence?.tracks ?? []).flatMap((track) => track.clips ?? []);
}

/** 时间线上所有片段的 id。 */
export function clipIdsOf(sequence: Sequence | null): string[] {
  return clipsOf(sequence).map((clip) => clip.id);
}
