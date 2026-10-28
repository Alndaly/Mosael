import type { VoiceOption } from "@/api/domains/speech";

/**
 * 测试用的一项音色目录(`GET /api/tts/voices` 的一行,ADR 0087)。只写这条用例在乎的那几格,其余取「什么都没声明」——
 * 和后端「宁缺不猜」同一个默认:没说语言就是空,不是中文。`VoiceOption` 多一格时只改这里。
 */
export function voiceOption(id: string, label = id, overrides: Partial<VoiceOption> = {}): VoiceOption {
  return {
    id,
    label,
    source: "builtin",
    languages: [],
    gender: "",
    styles: [],
    models: [],
    preview_url: "",
    extra: {},
    is_default: false,
    ...overrides,
  };
}
