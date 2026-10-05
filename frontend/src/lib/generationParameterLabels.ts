import type { GenerationOption } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { countsRuns, declaredParameters, type GenerationKind } from "@/lib/generationCapabilities";

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

/** 枚举参数下面的那句说明:选哪一档会差多少钱这种,用户在选的那一刻就该知道的事。 */
export const GENERATION_PARAMETER_HINTS: Record<string, MessageKey> = {
  quality: "genQualityPriceHint",
};

/** 宿主给了专门控件的那几个参数(比例、尺寸、分辨率、张数、时长、歌词、种子)叫什么。 */
const HOST_PARAMETER_LABELS: Record<string, MessageKey> = {
  aspect_ratio: "wfGenAspectRatio",
  size: "wfGenSize",
  resolution: "wfGenResolution",
  num_images: "wfGenNumImages",
  duration_seconds: "wfGenDuration",
  lyrics: "genLyrics",
  seed: "wfGenSeed",
};

/**
 * **工作流里一个生成参数叫什么。** 「AI 生成素材」检查器里那一格的标题,和画布上引用写在那一格里时的输入口
 * (workflows/portNames),读的都是这一个函数 —— 此前画布上的口叫 `aspect_ratio`,检查器里叫「画面比例」。
 *
 * 宿主认得的按界面语言给;模型自己声明的参数(插件生成供应商的 `parameter_schema`)用它声明的名字。
 * 都说不出来回空串,由调用方决定退回什么(键名本身)。`model` 可以是 null:模型清单还没到、或节点还没选模型时,
 * 宿主认得的那几个照样有名字。
 */
export function generationParameterLabel(
  key: string,
  model: GenerationOption | null,
  t: (key: MessageKey) => string,
): string {
  // ComfyUI 工作流的「张数」是跑几遍(countsRuns,每遍按工作流原样出它那一批):照实叫「跑几遍」—— AI 工作台、画板、
  // 工作流节点的表单和画布上的接入点都读这里,同一格不会一处叫「张数」一处叫「跑几遍」。
  if (key === "num_images" && countsRuns(model)) return t("genRuns");
  const known = HOST_PARAMETER_LABELS[key] ?? GENERATION_BOOLEAN_LABELS[key] ?? GENERATION_PARAMETER_LABELS[key];
  if (known) return t(known);
  return declaredParameters(model).find((parameter) => parameter.key === key)?.label ?? "";
}
