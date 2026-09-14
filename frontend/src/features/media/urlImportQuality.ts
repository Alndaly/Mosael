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

/** 上限提示该说哪一句 —— 没有可说的就别占一行。 */
export type QualityHint =
  | { key: "urlImportQualityKnown"; n: number }
  | { key: "urlImportQualityKnownSignedIn"; n: number; name: string };

/**
 * 「这个链接最高只有 {n}p」后面该跟哪句话。
 *
 * 跟的那句此前恒定是「需要更高画质就选一个登录身份再试」。**可挑过身份的人读到它只会困惑**:
 * 我不是选了吗?这时真正该说的是另一件事 —— 这个上限就是内容本身的,而且已经是拿着这个
 * 身份探到的了,再换一个也不会更高。
 *
 * 建议只对「还没挑」的人才成立;对挑过的人,同一句话就成了错的指路。
 */
export function qualityHint(bestKnown: number, signedInAs: string): QualityHint | null {
  if (bestKnown <= 0) return null;
  return signedInAs
    ? { key: "urlImportQualityKnownSignedIn", n: bestKnown, name: signedInAs }
    : { key: "urlImportQualityKnown", n: bestKnown };
}
