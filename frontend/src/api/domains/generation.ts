import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type GenerationOption = components["schemas"]["GenerationOptionOut"];
export type GenerationJob = components["schemas"]["GenerationJobOut"];
export type GenerationCreateResponse = components["schemas"]["GenerationCreateResponse"];

export type PromptOptimizeResult = components["schemas"]["PromptOptimizeResponse"];

/** 一条连接上的模型行,生成参数可以「和哪个内置模型一样」或「用哪份参数组」—— 模型设置弹窗的那一格。
 *  后端回的是无类型的字典,形状以这里为准。 */
export type CapabilityRefs = {
  models: { value: string; provider: string; model: string; parameter_keys: string[] }[];
  profiles: { value: string; profile: string; parameter_keys: string[]; custom?: boolean; id?: string }[];
  /** 什么都不指时,这条通道本身给得出哪几项。**空 = 真的只剩提示词**;非空 = 键知道了,
   *  但没人验证过这个模型收哪些取值。这两种处境要分开说。 */
  fallback_keys?: string[];
};

export function listCapabilityRefs(kind: string, profileId: string): Promise<CapabilityRefs> {
  return api<CapabilityRefs>(`/api/generation/capability-refs?kind=${encodeURIComponent(kind)}&profile_id=${profileId}`);
}

/** Rewrite an image prompt according to the selected provider and model conventions. */
export function optimizeImagePrompt(body: {
  workspace_id: string;
  provider: string;
  model: string;
  prompt: string;
  provider_profile_id?: string | null;
  language?: string;
}): Promise<PromptOptimizeResult> {
  return api<PromptOptimizeResult>("/api/generation/optimize-prompt", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * 重新取回一条失败了的生成:服务商那边已经做完(或还在做)的那个远端任务,**不重新提交、不再付钱**,再问它要一次结果
 * (下载成片时断了、等远端时钥匙失效之类,见后端 generation.use_cases.retrieve)。只对 `retrievable` 的记录有效。
 * 回来的是挂到这条记录上的新任务。
 */
export function retrieveGeneration(generationId: string): Promise<GenerationCreateResponse> {
  return api<GenerationCreateResponse>(`/api/generation/jobs/${encodeURIComponent(generationId)}/retrieve`, { method: "POST" });
}

/** 这种生成能用哪些(连接 × 模型)。设置页里加了什么,这里就有什么。 */
export function listGenerationOptions(kind: string): Promise<GenerationOption[]> {
  return api<GenerationOption[]>(`/api/generation/options?kind=${encodeURIComponent(kind)}`);
}

export type UnavailableModel = components["schemas"]["GenerationUnavailableOut"];

/** 插件连接上「认得、现在用不了」的模型和为什么(ComfyUI:表单还是旧格式,到工作流库里升级)。 */
export function listUnavailableModels(): Promise<UnavailableModel[]> {
  return api<UnavailableModel[]>("/api/generation/unavailable");
}
