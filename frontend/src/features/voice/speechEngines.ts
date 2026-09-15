import type { components } from "@/api/generated/schema";

export type TtsEngineChoice = components["schemas"]["TtsEngineChoiceOut"];

/**
 * 能拿来「念一句话」的引擎。
 *
 * **播客引擎不在其中**:它一次产出一整段双人对话,而这里是一条字幕、一张便签 —— 形状根本
 * 不同,摆出来只会得到一段对不上的音频,而用户要到听的时候才发现。
 *
 * 住在 features/voice 而不是 features/editor:字幕配音和画板的音频卡片问的是同一个问题,
 * 各写一份的结果是其中一处日后长出第二个播客引擎也没人记得排除。
 */
export function speechEngineChoices(engines: TtsEngineChoice[] | undefined): TtsEngineChoice[] {
  return (engines ?? []).filter((engine) => engine.id !== "volcano-podcast");
}

/**
 * 紧凑工具行(画板的音频卡片)里能摆出来的引擎。
 *
 * 比字幕面板那份**再紧一档**:要求引擎自己报得出音色清单。报不出的(百炼那种开放模型集合,
 * 得手打一个 model id)在设置页和字幕面板里有地方输入,而节点下面这一行只有一个下拉 ——
 * 摆一个点开是空的下拉,就是这个仓库一直在消灭的那种"点了没反应"。
 *
 * 克隆那条例外:它的音色来自工作区的配音库,不在引擎描述符里。
 */
export function compactSpeechEngineChoices(engines: TtsEngineChoice[] | undefined): TtsEngineChoice[] {
  return speechEngineChoices(engines).filter(
    (engine) => engine.id === "clone" || (engine.voices ?? []).length > 0,
  );
}
