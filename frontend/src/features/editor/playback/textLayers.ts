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
  /** 每条字幕在字幕框里排第几道(clip id → 道)。见 subtitleLanes。 */
  subtitleLanes: Record<string, number>;
}

/** 文本片段:没有素材、有文字。放在 video 轨上就是花字。 */
export function isTextClip(clip: Clip): boolean {
  return !clip.asset_id && Boolean(clip.text_override);
}

export function textLayers(tracks: Track[]): TextLayers {
  const shown = tracks.filter((track) => track.kind === "subtitle" && !track.hidden);
  const subtitles = shown.flatMap((track) => track.clips ?? []);
  const titles = tracks
    .filter((track) => track.kind === "video")
    .sort((a, b) => a.position - b.position)
    .flatMap((track) => (track.clips ?? []).filter(isTextClip));
  return { subtitles, titles, subtitleLanes: subtitleLanes(shown) };
}

/**
 * 每条字幕在字幕框里排第几「道」:显示着、有字幕的字幕轨按 position 升序(= 时间线上从上到下)排,
 * 第几条就是第几道,道 0 在框的最上面。
 *
 * 按时间线顺序而不是认「原文 / 译文」:字幕轨上没有这种标记(role 只给配音轨用,翻译功能把译文写回
 * 同一条字幕)。新建的字幕轨缺省放在最下面,所以先有的原文轨默认在上;要换就在时间线上挪轨道。空轨不占道。
 * 导出侧是 scene.subtitle_lanes。
 */
function subtitleLanes(shown: Track[]): Record<string, number> {
  const lanes: Record<string, number> = {};
  shown
    .filter((track) => (track.clips ?? []).length > 0)
    .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
    .forEach((track, lane) => {
      for (const clip of track.clips ?? []) lanes[clip.id] = lane;
    });
  return lanes;
}

/** 一条字幕要画的字:去掉首尾空白。只剩空白就是不画。 */
function subtitleText(clip: Clip): string {
  return (clip.text_override ?? "").trim();
}

/**
 * 此刻在场的几条字幕合成**一框**:按道从上到下一道一行(一条字幕自己有几行就占几行),空白的不占行。
 *
 * 合成一框、框整体按字幕样式定位(底部时下沿不动往上长,顶部时上沿不动往下长):每道此刻几行高由排版
 * 自己决定,预览(一个 DOM 元素)和导出(同一套 CSS 渲染的一张 PNG、或一条 libass Dialogue)不用各算
 * 一遍高度;「分两条轨」和「同一条轨里写两行」也因此是同一个画面。同一道上真有两条同时在场时按开始
 * 时间、再按 id 排。导出侧是 scene.stacked_subtitle_text / subtitle_frames,contracts/text-layer-cases.json 钉住。
 */
export function stackedSubtitleText(present: Clip[], lanes: Record<string, number>): string {
  const byId = (a: Clip, b: Clip) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  return present
    .filter((clip) => subtitleText(clip))
    .sort((a, b) => (lanes[a.id] ?? 0) - (lanes[b.id] ?? 0) || a.timeline_start - b.timeline_start || byId(a, b))
    .map(subtitleText)
    .join("\n");
}
