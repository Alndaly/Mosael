/** 逐字稿里的说话人:什么时候值得占一块地方,以及占的时候长什么样。 */

import type { MessageKey } from "@/app/messages";

const ENGINE_PREFIX = "SPEAKER_";

/** 说话人配色:名字哈希到色相,同一个人永远同色。 */
export function speakerHue(speaker: string): number {
  let hash = 0;
  for (const ch of speaker) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return hash % 360;
}

/**
 * 只有**分得出两个人**的时候,说话人标签才有信息量。
 *
 * 单人访谈、口播、屏幕录制是最常见的输入,而它们每一句前面都挂着同一个「说话人 00」——
 * 每行都一样的东西不是标签,是噪声:它把正文往右推,还抢走第一眼。
 */
export function speakersAreMeaningful(speakers: readonly (string | null | undefined)[]): boolean {
  const named = new Set<string>();
  for (const speaker of speakers) {
    const trimmed = (speaker ?? "").trim();
    if (trimmed) named.add(trimmed);
    if (named.size > 1) return true;
  }
  return false;
}

/**
 * 引擎编号(`SPEAKER_00`)换成给人看的序号:**从 1 数,不补零**。
 *
 * 此前原样截出 `00` 摆在时间码 `00:00.4` 旁边 —— 读起来像时间码多出来的两位,
 * 用户问"这个绿色的 00 是什么"。数人从 1 数起。不是引擎写法的(人名)返回 null。
 */
function speakerOrdinal(speaker: string): string | null {
  const at = speaker.indexOf(ENGINE_PREFIX);
  if (at < 0) return null;
  const raw = speaker.slice(at + ENGINE_PREFIX.length).trim();
  return /^\d+$/u.test(raw) ? String(Number(raw) + 1) : raw || null;
}

/** `SPEAKER_00` 是引擎的写法,不是给人看的。 */
export function speakerLabel(speaker: string, t: (key: MessageKey) => string): string {
  const ordinal = speakerOrdinal(speaker);
  if (ordinal === null) return speaker;
  return speaker.slice(0, speaker.indexOf(ENGINE_PREFIX)) + t("transcriptSpeakerLabel").replace("{n}", ordinal);
}

/**
 * 时间码那一栏只有几十像素,放不下「说话人 1」。
 *
 * 放得下的是序号本身(前面配一个人形图标,见 TranscriptPanel):那一栏里上下排着的都是说话人,
 * `1` / `2` 足够分辨,完整名字挂在 title 上。
 */
export function speakerShort(speaker: string): string {
  return speakerOrdinal(speaker) ?? speaker;
}

/**
 * 标签配色跟着主题走。
 *
 * 此前是写死的 `oklch(0.94 …)` 背景 —— 浅色下正好,深色下就是一块打在暗面板上的亮斑。
 * 和 `--background` 混一次,两套主题各自成立。
 */
export function speakerChipStyle(speaker: string): { background: string; color: string } {
  const hue = speakerHue(speaker);
  const ink = `oklch(0.62 0.13 ${hue})`;
  return {
    background: `color-mix(in oklab, ${ink} 16%, var(--background))`,
    color: `color-mix(in oklab, ${ink} 88%, var(--foreground))`,
  };
}
