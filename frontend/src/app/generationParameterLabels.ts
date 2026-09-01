import type { MessageKey } from "@/app/messages";

/** 能力描述符里的布尔参数 → UI 文案。未知的新参数仍可回落显示参数名。 */
export const GENERATION_BOOLEAN_LABELS: Record<string, MessageKey> = {
  generate_audio: "genGenerateAudio",
  multi_shot: "genMultiShot",
  camera_fixed: "genCameraFixed",
  prompt_extend: "genPromptExtend",
};

/** 供应商枚举参数的共用文案；三个生成入口只消费，不彼此反向依赖。 */
export const GENERATION_PARAMETER_LABELS: Record<string, MessageKey> = {
  quality: "genQuality",
  background: "genBackground",
  output_format: "genOutputFormat",
  moderation: "genModeration",
};
