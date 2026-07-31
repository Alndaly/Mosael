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

export function imageSizeOptions(model: GenerationModel | null): string[] {
  if (!supportsParameter(model, "size")) return [];
  return capabilityList(model, "sizes", FALLBACK_IMAGE_SIZES);
}

export function videoResolutionOptions(model: GenerationModel | null): string[] {
  if (!supportsParameter(model, "resolution")) return [];
  return capabilityList(model, "resolutions", FALLBACK_VIDEO_RESOLUTIONS);
}

export function aspectRatioOptions(model: GenerationModel | null): string[] {
  if (!supportsParameter(model, "aspect_ratio")) return [];
  return capabilityList(model, "aspect_ratios", FALLBACK_ASPECT_RATIOS);
}

export function durationOptions(model: GenerationModel | null): number[] {
  if (!supportsParameter(model, "duration_seconds")) return [];
  return capabilityNumberList(model, "duration_seconds", [5]);
}

export function maxImages(model: GenerationModel | null): number {
  return capabilityNumber(model, "max_num_images", 4);
}

