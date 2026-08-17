/**
 * 画质档位。
 *
 * **上限而不是精确值**:同一批里每条能给的画质并不一样,要求"正好 1080p"会让没有这一档的
 * 那些直接失败;要"不超过 1080p"则每条都取它自己能给的最好的那一档。
 *
 * 而且要**只列这条链接真有的档**。不带登录态的 YouTube 现在只给到 360p(实测),摆一个
 * 「2160p」让人选、下回来一个 360p,是让界面替站点撒谎。探测拿到 heights 就按它裁剪;
 * 拿不到(播放列表只做浅层探测)才给通用档位 —— 那时"未知"是诚实的。
 */
export const QUALITY_STEPS = [2160, 1440, 1080, 720, 480, 360] as const;

/** 0 表示不限;它永远排第一。 */
export function qualityOptions(heights: readonly number[]): number[] {
  if (heights.length === 0) return [0, ...QUALITY_STEPS];
  const best = Math.max(...heights);
  // 比这条视频最高画质还高的档位没有意义 —— 选了也只会拿到同一个流。
  return [0, ...QUALITY_STEPS.filter((step) => step < best)];
}

/** 这一批里能确证的最高画质;没有一条给出 heights 时返回 0(未知)。 */
export function knownBestHeight(entries: readonly { heights?: number[] }[]): number {
  const all = entries.flatMap((entry) => entry.heights ?? []);
  return all.length > 0 ? Math.max(...all) : 0;
}
