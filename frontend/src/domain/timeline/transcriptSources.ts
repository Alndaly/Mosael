import type { Clip, Track } from "@/api/client";

/**
 * 逐字稿(和「从逐字稿生成字幕」「转写其余 N 段」)看哪些片段。**两处共用这一份**:逐字稿面板和生成字幕
 * 此前各写一遍「V1 + 所有音频轨」,而那会把不该算的也算进去 ——
 *
 *   - **配音轨**(role=dub):配上去的是译文的声音,转写它得到的是另一种语言的逐字稿,还会被
 *     「转写其余 N 段」当成没转过的素材去转一遍(真实的耗时调用)。
 *   - **分离出来的人声 / 背景音**(素材 source=separated):说的是原片里的同一段话,算进去每句话出现两遍。
 *   - **同一段素材在视频轨和分离出的音频上各一份**(分离音频之后,视频片段静音、音频轨上多一段同素材、
 *     同位置的片段):只留视频轨那一份,不然逐字稿每句重复。
 */
export function transcriptSourceClips(tracks: readonly Track[]): Clip[] {
  const main = tracks.find((track) => track.kind === "video");
  const audio = tracks.filter((track) => track.kind === "audio" && track.role !== "dub");
  const seen = new Set<string>();
  const clips: Clip[] = [];
  for (const clip of [...(main?.clips ?? []), ...audio.flatMap((track) => track.clips ?? [])]) {
    if (clip.asset_source === "separated") continue;
    const key = clip.asset_id
      ? [clip.asset_id, clip.timeline_start, clip.src_in, clip.src_out].map((value) =>
          typeof value === "number" ? value.toFixed(3) : value,
        ).join("|")
      : clip.id;
    if (seen.has(key)) continue;
    seen.add(key);
    clips.push(clip);
  }
  return clips;
}
