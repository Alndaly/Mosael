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

/** 再来一次:照这一条记着的模型和参数重新提交一次,收在同一条会话里(和发送一样花钱)。只对 `repeatable` 的记录有效。 */
export function repeatGeneration(generationId: string): Promise<GenerationCreateResponse> {
  return api<GenerationCreateResponse>(`/api/generation/jobs/${encodeURIComponent(generationId)}/again`, { method: "POST" });
}

/**
 * 重新取回一条失败了的生成:服务商那边已经做完(或还在做)的那个远端任务,**不重新提交、不再付钱**,再问它要一次结果
 * (下载成片时断了、等远端时钥匙失效之类,见后端 generation.use_cases.retrieve)。只对 `retrievable` 的记录有效。
 * 回来的是挂到这条记录上的新任务。
 */
export function retrieveGeneration(generationId: string): Promise<GenerationCreateResponse> {
  return api<GenerationCreateResponse>(`/api/generation/jobs/${encodeURIComponent(generationId)}/retrieve`, { method: "POST" });
}

type SpeechCreateIn = components["schemas"]["SpeechCreate"];
type PodcastCreateIn = components["schemas"]["PodcastCreate"];
/** 请求体:后端有缺省值的几格可以不给。 */
export type SpeechCreate = Pick<SpeechCreateIn, "workspace_id" | "text" | "engine" | "voice">
  & Partial<Omit<SpeechCreateIn, "workspace_id" | "text" | "engine" | "voice">>;
export type PodcastCreate = Pick<PodcastCreateIn, "workspace_id" | "mode"> & Partial<Omit<PodcastCreateIn, "workspace_id" | "mode">>;

/**
 * 创作页「语音」:念一段字,记成会话里的一条(ADR 0055)。没带会话就由后端现开一条(回执里的 `generation.session_id`)。
 * 远端引擎念配音库里的嗓子、这个账号还没同意上传时回 409(见 speech.ts 的 `remoteConsentRequest`)。
 */
export function createSpeech(body: SpeechCreate): Promise<GenerationCreateResponse> {
  return api<GenerationCreateResponse>("/api/generation/speech", { method: "POST", body: JSON.stringify(body) });
}

/** 创作页「播客」:改写材料、聊一个主题、照稿念(ADR 0055 §6)。 */
export function createPodcast(body: PodcastCreate): Promise<GenerationCreateResponse> {
  return api<GenerationCreateResponse>("/api/generation/podcast", { method: "POST", body: JSON.stringify(body) });
}

/** 这种生成能用哪些(连接 × 模型)。设置页里加了什么,这里就有什么。 */
export function listGenerationOptions(kind: string): Promise<GenerationOption[]> {
  return api<GenerationOption[]>(`/api/generation/options?kind=${encodeURIComponent(kind)}`);
}

export type MissingGenerationModel = components["schemas"]["GenerationMissingOut"];

/**
 * 记着的 (连接, 模型) 不在生成选项里时:它叫什么、为什么不在、怎么修(连接删了停了、模型停了;ComfyUI:表单删了、工作流改名
 * 挪走删了、表单是旧格式要升级)。插件连接会去问插件。
 */
export function getMissingModel(providerProfileId: string, model: string, kind: string): Promise<MissingGenerationModel> {
  const query = new URLSearchParams({ provider_profile_id: providerProfileId, model, kind });
  return api<MissingGenerationModel>(`/api/generation/missing?${query.toString()}`);
}
