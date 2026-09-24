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

/**
 * 这台机器上**确定**没有能跑的转写引擎吗。
 *
 * 模型权重首次转写时会自己下,真正拦路的是运行环境(装了 funasr/whisperx 的解释器)——
 * 那个要在设置页装一次,转写不会替你拉几个 GB 的依赖。所以只看 `runtime_ready`。
 *
 * **只有测过了、全都跑不起来才算"没有"。** 探测要起子进程 import torch,刚打开时可能还没有答案;
 * 拿"还没测"当"没有"去拦按钮,就是拿一个未知冒充结论。列表拿不到(空、还在读)同理,不拦 ——
 * 真转不了,任务自己会说为什么。
 */
export function asrEngineMissing(
  models: readonly { runtime_ready?: boolean; runtime_checked?: boolean }[] | undefined,
): boolean {
  if (!models || models.length === 0) return false;
  if (models.some((model) => model.runtime_ready)) return false;
  return models.every((model) => model.runtime_checked);
}
