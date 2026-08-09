/**
 * 字节数和速度的人话写法。**一份**。
 *
 * 此前 `AsrModelsSection` 和 `VoiceCloneSection` 各抄了一份一模一样的 `fmtBytes`/`fmtSpeed`,
 * 而配音面板又差点抄第三份。抄第三份的代价不是多几行,是三份会各自漂移。
 */

/** KB 这一档是补的:两份旧实现最小只到 MB,于是一个 300KB 的参考音频显示成「0 MB」。 */
export function formatBytes(n: number): string {
  if (n <= 0) return "0 MB";
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)} GB`;
  if (n >= 1_000_000) return `${Math.round(n / 1_000_000)} MB`;
  return `${Math.max(1, Math.round(n / 1000))} KB`;
}

export function formatSpeed(bytesPerSecond: number): string {
  if (bytesPerSecond <= 0) return "";
  if (bytesPerSecond >= 1_000_000) return `${(bytesPerSecond / 1_000_000).toFixed(1)} MB/s`;
  return `${Math.round(bytesPerSecond / 1000)} KB/s`;
}
