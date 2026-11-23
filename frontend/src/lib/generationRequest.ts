/**
 * **生成请求的参数怎么拼,只有这一处。**
 *
 * AI 工作台、画板节点、工作流节点各有各的界面状态,但发出去的参数遵守同一条规则:
 * **模型声明了某个参数 → 有值就发;没声明 → 一定不发。** 不按图像 / 视频 / 音频分支。
 *
 * 收之前这条规则抄了三份,靠「和画板同一条」这类注释对齐,结果还是漂了:图像模型声明了
 * `aspect_ratio` 时画板会发,AI 工作台的图像分支从不发、界面也把那一栏藏了。
 *
 * 各入口只负责把自己的状态映射成 {@link GenerationForm};空串 / undefined 一律表示「没填」。
 */
import type { GenerationOption } from "@/api/client";

import {
  DURATION_UNSET,
  booleanParameterKeys,
  capabilityBoolean,
  capabilityString,
  declaredParameterValue,
  declaredParameters,
  maxImages,
  parameterChoiceEntries,
  supportsParameter,
} from "./generationCapabilities";
import { frameUrlParameters, type FrameSlots } from "./sourceFrames";

/** 有专属控件的布尔参数 —— 不进「调参」那一串通用开关,免得同一个开关出现两次。 */
export const DEDICATED_BOOLEANS: ReadonlySet<string> = new Set(["generate_audio", "instrumental"]);

/** 一次生成的表单值。哪一栏这个入口没有,就不给。 */
export interface GenerationForm {
  size?: string;
  resolution?: string;
  aspectRatio?: string;
  /** 秒数;undefined 或 {@link DURATION_UNSET} = 让模型用它自己的默认。 */
  durationSeconds?: number;
  generateAudio?: boolean;
  /** 一次出几张;发之前夹到 [1, 模型上限]。 */
  numImages?: number;
  /** 原文;空串 = 不发。 */
  seed?: string;
  instrumental?: boolean;
  lyrics?: string;
  /** 外链形式的输入素材(首帧 / 尾帧 / 参考图……的 url)。 */
  frames?: FrameSlots;
  /** 通用开关;没动过的取模型声明的默认。 */
  booleanParameters?: Readonly<Record<string, boolean>>;
  /** 供应商特有的枚举;没动过的取模型声明的默认。 */
  enumParameters?: Readonly<Record<string, string>>;
  /** 模型自己声明的参数(`parameter_schema`)里用户动过的那些,存控件原文。 */
  declared?: Readonly<Record<string, string>>;
}

export type GenerationParameters = Record<string, string | number | boolean | string[]>;

export function requestParameters(model: GenerationOption | null, form: GenerationForm): GenerationParameters {
  const declares = (key: string) => supportsParameter(model, key);
  const params: GenerationParameters = {};

  //: 出多大:图像收 `1024x1024`,万相视频收 `832*480`,火山 / 可灵收 720p 档位 —— 都按声明发。
  if (declares("size") && form.size) params.size = form.size;
  if (declares("resolution") && form.resolution) params.resolution = form.resolution;
  if (declares("aspect_ratio") && form.aspectRatio) params.aspect_ratio = form.aspectRatio;
  if (declares("num_images") && form.numImages !== undefined) {
    params.num_images = Math.max(1, Math.min(maxImages(model), Math.floor(form.numImages) || 1));
  }
  //: 不在前端夹时长:-1 这类特殊值会被夹坏,真正非法的值由统一校验器明确报错(ADR 0015)。
  if (declares("duration_seconds") && form.durationSeconds !== undefined && form.durationSeconds !== DURATION_UNSET) {
    params.duration_seconds = form.durationSeconds;
  }
  //: 布尔值两边都显式发:只在 true 时发,「静音」会落回供应商默认 —— Seedance 2.5 默认有声,
  //: 于是界面显示静音、成片却带声音。
  if (declares("generate_audio") && form.generateAudio !== undefined) params.generate_audio = form.generateAudio;
  if (declares("instrumental") && form.instrumental !== undefined) params.instrumental = form.instrumental;
  //: 纯音乐不带歌词 —— 两个都发,各家要么报错、要么悄悄丢掉歌词。
  if (declares("lyrics") && !form.instrumental && form.lyrics?.trim()) params.lyrics = form.lyrics;
  if (declares("seed") && form.seed?.trim()) params.seed = Number(form.seed);

  for (const key of booleanParameterKeys(model)) {
    if (DEDICATED_BOOLEANS.has(key)) continue;
    params[key] = form.booleanParameters?.[key] ?? capabilityBoolean(model, `default_${key}`);
  }
  for (const [key, choices] of parameterChoiceEntries(model)) {
    const value = form.enumParameters?.[key] ?? capabilityString(model, `default_${key}`, choices[0] ?? "");
    if (value) params[key] = value;
  }
  //: 模型自己声明的参数**只发用户动过的**:插件给的默认值只是占位,原样发回去会把
  //: 「我没选过」变成「我选了这个」(ADR 0015)。
  for (const parameter of declaredParameters(model)) {
    const value = declaredParameterValue(parameter, form.declared?.[parameter.key] ?? "");
    if (value !== undefined) params[parameter.key] = value;
  }
  if (form.frames) Object.assign(params, frameUrlParameters(form.frames, declares));
  return params;
}
