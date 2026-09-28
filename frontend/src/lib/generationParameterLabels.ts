import type { MessageKey } from "@/app/messages";
import type { GenerationKind } from "@/lib/generationCapabilities";

/** 生成种类 → 界面上的名字。选择器分组、工作流节点、配置提示都读这一份。 */
export const GENERATION_KIND_LABELS: Record<GenerationKind, MessageKey> = {
  image: "capImage",
  video: "capVideo",
  audio: "capAudio",
};

/** 能力描述符里的布尔参数 → UI 文案。未知的新参数仍可回落显示参数名。 */
export const GENERATION_BOOLEAN_LABELS: Record<string, MessageKey> = {
  generate_audio: "genGenerateAudio",
  multi_shot: "genMultiShot",
  camera_fixed: "genCameraFixed",
  prompt_extend: "genPromptExtend",
  instrumental: "genInstrumentalOnly",
  asmr_mode: "genAsmrMode",
};

/** 供应商枚举参数的共用文案；三个生成入口只消费，不彼此反向依赖。 */
export const GENERATION_PARAMETER_LABELS: Record<string, MessageKey> = {
  quality: "genQuality",
  background: "genBackground",
  output_format: "genOutputFormat",
  moderation: "genModeration",
  // 音频(ADR 0022):模型自己声明的参数(parameter_schema)里宿主认得的那几个,按界面语言说。
  vocal_gender: "genVocalGender",
  title: "genSongTitle",
  bgm_prompt: "genBgmPrompt",
  model_version: "genModelVersion",
};
