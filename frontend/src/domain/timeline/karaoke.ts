import type { ProjectableClip, TokenLike } from "./transcriptProjection";

/**
 * 一个词在**时间线上**占的那一段。
 *
 * 卡拉OK高亮此前是反过来问的:先遍历片段取"第一个覆盖播放头的",再拿它的 id 和句子比对。
 * 而视频轨和音频轨在时间上重叠是常态 —— 逐字稿来自音频片段,视频片段却排在前面,于是
 * "当前片段"总是命中视频那个,和逐字稿对不上。
 *
 * 换个方向就没有这个问题:不问"当前是哪个片段",而是问"这个词落在哪儿"。词自己知道它属于
 * 哪个片段、在源时间的什么位置,映回时间线是确定的一步(倍速也在这一步里算掉:2 倍速下
 * 源里的两秒是时间线上的一秒)。
 */
export function tokenTimelineRange(
  clip: ProjectableClip | undefined,
  token: Pick<TokenLike, "start_time" | "end_time">,
): [number, number] | null {
  if (!clip) return null;
  const speed = clip.speed || 1;
  const at = (src: number) => clip.timeline_start + (src - clip.src_in) / speed;
  return [at(token.start_time), at(token.end_time)];
}
