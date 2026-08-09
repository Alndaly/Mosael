/**
 * 「转全部可转写的素材」要转哪些。
 *
 * 两条判据合起来才对:
 *
 *   - **能不能转**:片段的 `asset_kind` 是 video/audio。视频轨上完全可以放图片(AI 生成的静图
 *     就是这么落上去的),而图片没有声音 —— 按轨道类型收的话会挑中它们。
 *   - **要不要转**:已经有逐字稿的跳过。转写是一次真实的付费/耗时调用,重复转同一个素材
 *     除了浪费没有别的效果,而用户点的是「转写这条时间线」,不是「重转一遍」。
 *
 * 顺序按它们在时间线上出现的顺序 —— 那也是用户读逐字稿的顺序,先转到的先能读。
 */
export function pendingTranscribeIds(assetIds: string[], hasTranscript: (assetId: string) => boolean): string[] {
  return assetIds.filter((assetId) => !hasTranscript(assetId));
}
