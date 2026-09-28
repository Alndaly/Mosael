import type { Clip, Track } from "@/api/client";

/**
 * 画面上的文字层:字幕和花字。它们不进 sceneLayersAt(那里只有素材画面),由监视器单独画在最上面。
 *
 * 轨道上两个开关各管一件事:`hidden` 只管字幕显示,`muted` 只管声音 —— 所以静音视频轨上的花字
 * 照旧显示。导出侧的等价实现是 `backend/app/media/scene.py` 的 `text_layers`,两侧由
 * `contracts/text-layer-cases.json` 钉死(见 textLayers.parity.test.ts)。
 */
export interface TextLayers {
  /** 没隐藏的字幕轨上的全部片段。 */
  subtitles: Clip[];
  /** video 轨上的花字:没有素材、有文字的片段。 */
  titles: Clip[];
}

/** 文本片段:没有素材、有文字。放在 video 轨上就是花字。 */
export function isTextClip(clip: Clip): boolean {
  return !clip.asset_id && Boolean(clip.text_override);
}

export function textLayers(tracks: Track[]): TextLayers {
  const subtitles = tracks
    .filter((track) => track.kind === "subtitle" && !track.hidden)
    .flatMap((track) => track.clips ?? []);
  const titles = tracks
    .filter((track) => track.kind === "video")
    .sort((a, b) => a.position - b.position)
    .flatMap((track) => (track.clips ?? []).filter(isTextClip));
  return { subtitles, titles };
}
