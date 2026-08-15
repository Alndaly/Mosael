import type { components } from "@/api/generated/schema";

type TtsEngineChoice = components["schemas"]["TtsEngineChoiceOut"];

/**
 * 能拿来给字幕配音的引擎。
 *
 * **播客引擎不在其中**:它一次产出一整段双人对话,而这里是一条字幕一句话 —— 形状根本不同,
 * 摆出来只会得到一段和字幕对不上的音频,而用户要到听的时候才发现。
 */
export function dubEngineChoices(engines: TtsEngineChoice[] | undefined): TtsEngineChoice[] {
  return (engines ?? []).filter((engine) => engine.id !== "volcano-podcast");
}
