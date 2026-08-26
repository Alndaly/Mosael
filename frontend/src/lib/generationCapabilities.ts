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
import type { GenerationModel } from "@/api/client";

//: 目录没声明时的兜底。刻意保守:给一个能跑的常见值,而不是空(空会让参数区整个消失)。
export const FALLBACK_IMAGE_SIZES = ["1024x1024"];
export const FALLBACK_VIDEO_RESOLUTIONS = ["720p"];
export const FALLBACK_ASPECT_RATIOS = ["16:9"];

export function capabilityList(model: GenerationModel | null, key: string, fallback: string[]): string[] {
  const value = model?.capabilities?.[key];
  if (!Array.isArray(value)) return fallback;
  const items = value.map((item) => String(item).trim()).filter(Boolean);
  return items.length > 0 ? items : fallback;
}

export function capabilityNumberList(model: GenerationModel | null, key: string, fallback: number[]): number[] {
  const value = model?.capabilities?.[key];
  if (!Array.isArray(value)) return fallback;
  const items = value.map((item) => Number(item)).filter((item) => Number.isFinite(item) && item > 0);
  return items.length > 0 ? items : fallback;
}

export function capabilityString(model: GenerationModel | null, key: string, fallback: string): string {
  const value = model?.capabilities?.[key];
  return typeof value === "string" ? value : fallback;
}

export function capabilityNumber(model: GenerationModel | null, key: string, fallback: number): number {
  const value = Number(model?.capabilities?.[key]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

export function parameterKeys(model: GenerationModel | null): string[] {
  return capabilityList(model, "parameter_keys", []);
}

export function supportsParameter(model: GenerationModel | null, key: string) {
  const keys = parameterKeys(model);
  return keys.length === 0 || keys.includes(key);
}

/** 这个模型能出哪些尺寸。**不限图像** —— 万相视频收的也是 `宽*高` 的像素对,
 *  而名字里带 image 会让人以为视频不该有这一栏(它此前就是这么被漏掉的)。 */
export function sizeOptions(model: GenerationModel | null): string[] {
  if (!supportsParameter(model, "size")) return [];
  return capabilityList(model, "sizes", model?.kind === "video" ? [] : FALLBACK_IMAGE_SIZES);
}

export function videoResolutionOptions(model: GenerationModel | null): string[] {
  if (!supportsParameter(model, "resolution")) return [];
  return capabilityList(model, "resolutions", FALLBACK_VIDEO_RESOLUTIONS);
}

export function aspectRatioOptions(model: GenerationModel | null): string[] {
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
export function durationOptions(model: GenerationModel | null): number[] {
  if (!supportsParameter(model, "duration_seconds")) return [];
  const value = model?.capabilities?.duration_seconds;
  if (!Array.isArray(value)) return [5];
  return value.map((item) => Number(item)).filter((item) => Number.isFinite(item) && item > 0);
}

/** 时长是区间时的上下界;不是区间(或没声明上界)时返回 null。 */
export function durationRange(model: GenerationModel | null): { min: number; max: number } | null {
  if (durationOptions(model).length > 0) return null;
  const max = capabilityNumber(model, "max_duration_seconds", 0);
  if (max <= 0) return null;
  return { min: capabilityNumber(model, "min_duration_seconds", 1) || 1, max };
}

export function maxImages(model: GenerationModel | null): number {
  return capabilityNumber(model, "max_num_images", 4);
}

