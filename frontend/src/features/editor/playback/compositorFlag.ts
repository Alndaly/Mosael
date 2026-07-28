/**
 * 预览画面**只有一条路**:WebCodecs 解代理 → CanvasCompositor 合成到一张 canvas。
 *
 * 曾经并存一条 `<video>`/`<img>` 元素路作兜底,并带一个 localStorage 开关在两者间切。两条路的
 * 取景、层级与调色都对不齐,「预览长什么样」于是取决于当时走了哪条,同一个问题要按两套语义各查
 * 一遍。元素路与那个开关都已删除:少了可切换的对象,开关只能把画面切成全黑。
 *
 * 现在唯一的条件是**环境有没有 WebCodecs**;没有时不再降级,而是由 PreviewUnavailable 明说
 * (见 previewReadiness.ts 的其余几种状态)。
 */

/** WebCodecs 是否可用。缺失时没有画面预览——音频仍由 WebAudioMixer 播放。 */
export function compositorSupported(): boolean {
  return typeof VideoDecoder !== "undefined";
}
