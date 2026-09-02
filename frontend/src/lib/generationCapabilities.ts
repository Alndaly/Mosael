/**
 * 读生成模型的 capabilities。
 *
 * 目录(`/api/generation/models`)声明每个模型支持哪些参数、可选值和默认值:
 * `parameter_keys` / `aspect_ratios` / `resolutions` / `duration_seconds` …
 * 界面据此渲染,而不是各处硬编一份"视频有哪些比例"——硬编的那份会在目录更新后悄悄过时。
 *
 * 抽到这里是因为有两个消费方:AI Studio 的生成面板,和工作流「AI 生成素材」节点的参数区。
 * 同一份规则解释两遍,迟早会在某一处漏掉新参数。
 */
import type { GenerationOption } from "@/api/client";

//: 目录没声明时的兜底。刻意保守:给一个能跑的常见值,而不是空(空会让参数区整个消失)。
export const FALLBACK_IMAGE_SIZES = ["1024x1024"];
export const FALLBACK_VIDEO_RESOLUTIONS = ["720p"];
export const FALLBACK_ASPECT_RATIOS = ["16:9"];

export function capabilityList(model: GenerationOption | null, key: string, fallback: string[]): string[] {
  const value = model?.capabilities?.[key];
  if (!Array.isArray(value)) return fallback;
  const items = value.map((item) => String(item).trim()).filter(Boolean);
  return items.length > 0 ? items : fallback;
}

export function capabilityNumberList(model: GenerationOption | null, key: string, fallback: number[]): number[] {
  const value = model?.capabilities?.[key];
  if (!Array.isArray(value)) return fallback;
  const items = value.map((item) => Number(item)).filter((item) => Number.isFinite(item) && item > 0);
  return items.length > 0 ? items : fallback;
}

export function capabilityString(model: GenerationOption | null, key: string, fallback: string): string {
  const value = model?.capabilities?.[key];
  return typeof value === "string" ? value : fallback;
}

export function capabilityNumber(model: GenerationOption | null, key: string, fallback: number): number {
  const value = Number(model?.capabilities?.[key]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

/** 布尔默认值也属于模型契约。缺失时使用调用方给的保守默认。 */
export function capabilityBoolean(model: GenerationOption | null, key: string, fallback = false): boolean {
  const value = model?.capabilities?.[key];
  return typeof value === "boolean" ? value : fallback;
}

/**
 * 这个角色最多能挂几份。目录里没写就是 1 —— **保守的那一边**:多挂一份的下场是提交时被拒,
 * 少挂一份只是少一张参考图。
 *
 * 数字来自各家接口自己的报错(见后端 domain/generation/catalog 的 source_limits),
 * 不是我们定的:火山和海螺给九张参考图,万相给参考图 + 参考视频合计五份。
 */
/**
 * 这个角色**能挂几份**。
 *
 * **不是支持判定。** 没声明的角色它返回兜底的 1 —— 想问「这个模型认不认某个角色」,
 * 用 supportsParameter(它查描述符的 parameter_keys)。两者混用会让图片模型也长出首尾帧槽。
 */
export function sourceLimit(model: GenerationOption | null, role: string): number {
  const limits = model?.capabilities?.source_limits;
  if (!limits || typeof limits !== "object") return 1;
  const value = Number((limits as Record<string, unknown>)[role]);
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : 1;
}

/**
 * 互斥的角色分组。同一次生成只能用其中一组。
 *
 * 首尾帧决定成片的第一格和最后一格;参考素材一帧都不出现在成片里,只影响风格与主体 ——
 * 火山把这条画成硬约束(`first/last frame content cannot be mixed with reference media
 * content`)。界面照着它把另一组灰掉,免得用户挂满了才在提交时吃一个英文 400。
 */
export function exclusiveSourceGroups(model: GenerationOption | null): string[][] {
  const groups = model?.capabilities?.exclusive_source_groups;
  if (!Array.isArray(groups)) return [];
  return groups
    .filter((group): group is unknown[] => Array.isArray(group))
    .map((group) => group.map((role) => String(role)).filter(Boolean))
    .filter((group) => group.length > 0);
}

export function parameterKeys(model: GenerationOption | null): string[] {
  return capabilityList(model, "parameter_keys", []);
}

export function supportsParameter(model: GenerationOption | null, key: string) {
  if (key === "generate_audio" && model?.capabilities?.supports_generate_audio === true) return true;
  const declared = model?.capabilities?.parameter_keys;
  // 参数描述符是当前接口契约。缺失与明确为空都表示“不要猜”，否则前端会主动发送
  // 供应商未声明的尺寸、时长或素材角色，最终只会得到一次可以提前避免的 400。
  if (!Array.isArray(declared)) return false;
  return declared.map(String).includes(key);
}

/** 需要开关控件的参数。参数类型也是能力契约的一部分，不能在各页面各抄一张名单。 */
export function booleanParameterKeys(model: GenerationOption | null): string[] {
  const value = model?.capabilities?.boolean_parameters;
  if (!Array.isArray(value)) return [];
  return value.map(String).filter((key) => key && supportsParameter(model, key));
}

/** 供应商特有的枚举参数，例如 OpenAI quality/background/output_format。 */
export function parameterChoiceEntries(model: GenerationOption | null): Array<[string, string[]]> {
  const value = model?.capabilities?.parameter_choices;
  if (!value || typeof value !== "object") return [];
  return Object.entries(value as Record<string, unknown>)
    .filter(([key, choices]) => supportsParameter(model, key) && Array.isArray(choices))
    .map(([key, choices]) => [key, (choices as unknown[]).map(String).filter(Boolean)] as [string, string[]])
    .filter(([, choices]) => choices.length > 0);
}

/** 这个模型能出哪些尺寸。**不限图像** —— 万相视频收的也是 `宽*高` 的像素对,
 *  而名字里带 image 会让人以为视频不该有这一栏(它此前就是这么被漏掉的)。 */
export function sizeOptions(model: GenerationOption | null): string[] {
  if (!supportsParameter(model, "size")) return [];
  return capabilityList(model, "sizes", model?.kind === "video" ? [] : FALLBACK_IMAGE_SIZES);
}

export function videoResolutionOptions(model: GenerationOption | null): string[] {
  if (!supportsParameter(model, "resolution")) return [];
  return capabilityList(model, "resolutions", FALLBACK_VIDEO_RESOLUTIONS);
}

export function aspectRatioOptions(model: GenerationOption | null): string[] {
  if (!supportsParameter(model, "aspect_ratio")) return [];
  return capabilityList(model, "aspect_ratios", FALLBACK_ASPECT_RATIOS);
}

/**
 * 时长的**可选档位**。空数组有两种含义,要分开:
 *
 * - 模型不支持时长 → 空(上面那行);
 * - 支持,但它是个**区间**而不是几个档 → 也是空,由 min/max 说了算(见 durationRange)。
 *
 * 所以这里不能走 capabilityNumberList 的兜底 —— 那个兜底把空数组当成"没声明"、回落到
 * `[5]`,于是区间型的模型永远显示成一个只有 5 的下拉。Seedance 2 收 4–15 秒,而界面
 * 只给一个选项,正是这么来的。
 */
export function durationOptions(model: GenerationOption | null): number[] {
  if (!supportsParameter(model, "duration_seconds")) return [];
  const value = model?.capabilities?.duration_seconds;
  if (!Array.isArray(value)) return [5];
  return value.map((item) => Number(item)).filter((item) => Number.isFinite(item) && item > 0);
}

/** 区间以外的合法时长值，例如 Seedance 2.5 的 -1=自动。 */
export function durationSpecialValues(model: GenerationOption | null): number[] {
  if (!supportsParameter(model, "duration_seconds")) return [];
  const value = model?.capabilities?.duration_special_values;
  if (!Array.isArray(value)) return [];
  return value.map(Number).filter(Number.isFinite);
}

/** 时长是区间时的上下界;不是区间(或没声明上界)时返回 null。 */
export function durationRange(model: GenerationOption | null): { min: number; max: number } | null {
  if (durationOptions(model).length > 0) return null;
  const max = capabilityNumber(model, "max_duration_seconds", 0);
  if (max <= 0) return null;
  return { min: capabilityNumber(model, "min_duration_seconds", 1) || 1, max };
}

/** 所有可在 UI 中选择的时长值：特殊值、离散档位或完整整数区间。 */
export function durationChoices(model: GenerationOption | null, resolution = ""): number[] {
  const special = durationSpecialValues(model);
  const discrete = durationOptions(model);
  const range = durationRange(model);
  const regular = discrete.length > 0
    ? discrete
    : range
      ? Array.from({ length: Math.floor(range.max) - Math.ceil(range.min) + 1 }, (_, index) => Math.ceil(range.min) + index)
      : [];
  const byResolution = model?.capabilities?.duration_by_resolution;
  const constrained = byResolution && typeof byResolution === "object"
    ? (byResolution as Record<string, unknown>)[resolution]
    : undefined;
  const allowed = Array.isArray(constrained)
    ? constrained.map(Number).filter((item) => Number.isFinite(item) && item > 0)
    : regular;
  return [...new Set([...special, ...allowed])];
}

/** 默认时长允许是 -1；通用 capabilityNumber 有意只接收正数，不适合这里。 */
export function defaultDuration(model: GenerationOption | null, fallback = 5): number {
  const declared = Number(model?.capabilities?.default_duration_seconds);
  if (Number.isFinite(declared)) return declared;
  return durationChoices(model)[0] ?? fallback;
}

/** 工作流字符串表单写回类型化参数，避免 "false" 在 Python 中被 bool("false") 判成 true。 */
export function parseGenerationParameterInput(value: string): string | number | boolean {
  if (value === "true") return true;
  if (value === "false") return false;
  return /^-?\d+(\.\d+)?$/.test(value) ? Number(value) : value;
}

export function maxImages(model: GenerationOption | null): number {
  return capabilityNumber(model, "max_num_images", 4);
}
