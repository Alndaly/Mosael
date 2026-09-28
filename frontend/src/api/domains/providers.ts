/**
 * 模型服务商:连接、我的密钥、模型行、能力默认、授权登录、参数组、计价规则。后端在
 * `routes/settings/provider_*.py`,路径前缀都是 `/api/settings/`。
 *
 * 此前这一族没有 domain:约 60 处裸路径散在设置、管理、智能体、工作流十几个文件里,每个文件还各自
 * 重写一遍 `type ProviderProfile = components[…]`。缓存键见 `api/queryKeys.providerKeys`。
 */
import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

type Schemas = components["schemas"];

export type ProviderProfile = Schemas["ProviderProfileOut"];
export type VendorPreset = Schemas["VendorPresetOut"];
export type ProviderModel = Schemas["ProviderModelOut"];
export type ProviderModelUpdate = Schemas["ProviderModelUpdate"];
export type ProviderDefault = Schemas["ProviderDefaultOut"];
export type CapabilityModel = Schemas["CapabilityModelOut"];
export type ProviderHealth = Schemas["ProviderHealthOut"];
export type ProviderQuota = Schemas["ProviderQuotaOut"];
export type ProviderOAuthLogin = Schemas["OAuthLoginOut"];
export type GenerationProfile = Schemas["GenerationCapabilityProfileOut"];
export type PricingRule = Schemas["ProviderPricingRuleOut"];
export type PricingPrefill = Schemas["PricingPrefillOut"];

/** 模型可以出现在哪条执行通道上 —— 同一个能力下,智能体、直连、网关、自动化各看到的候选不同。 */
export type ModelSurface = "all" | "agent" | "direct" | "gateway" | "automation";

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });
const segment = (value: string) => encodeURIComponent(value);

// ── 连接与我的密钥 ─────────────────────────────────────────────────────────────

export function listProviderProfiles(): Promise<ProviderProfile[]> {
  return api<ProviderProfile[]>("/api/settings/providers");
}

export function listProviderVendors(): Promise<VendorPreset[]> {
  return api<VendorPreset[]>("/api/settings/provider-vendors");
}

export function createProviderProfile(body: Schemas["ProviderProfileCreate"]): Promise<ProviderProfile> {
  return api<ProviderProfile>("/api/settings/providers", json("POST", body));
}

export function updateProviderProfile(profileId: string, body: Schemas["ProviderProfileUpdate"]): Promise<ProviderProfile> {
  return api<ProviderProfile>(`/api/settings/providers/${profileId}`, json("PATCH", body));
}

export function deleteProviderProfile(profileId: string): Promise<void> {
  return api<void>(`/api/settings/providers/${profileId}`, { method: "DELETE" });
}

/** 我自己在这条连接上的密钥。和连接本身分开:普通成员改不了连接,但永远配得了自己的密钥。 */
export function setProviderCredential(profileId: string, body: Schemas["ProviderCredentialIn"]): Promise<Schemas["ProviderCredentialOut"]> {
  return api<Schemas["ProviderCredentialOut"]>(`/api/settings/providers/${profileId}/credential`, json("PUT", body));
}

export function probeProviderHealth(profileId: string): Promise<ProviderHealth> {
  return api<ProviderHealth>(`/api/settings/providers/${profileId}/health`);
}

/** 问供应商要一次额度。是 POST:每次都真的去问,不是读缓存。 */
export function fetchProviderQuota(profileId: string): Promise<ProviderQuota> {
  return api<ProviderQuota>(`/api/settings/providers/${profileId}/quota`, { method: "POST" });
}

// ── 订阅计划的授权登录 ─────────────────────────────────────────────────────────

export function startProviderOAuthLogin(profileId: string): Promise<ProviderOAuthLogin> {
  return api<ProviderOAuthLogin>(`/api/settings/providers/${profileId}/oauth/login`, { method: "POST" });
}

export function getProviderOAuthLogin(profileId: string, loginId: string): Promise<ProviderOAuthLogin> {
  return api<ProviderOAuthLogin>(`/api/settings/providers/${profileId}/oauth/login/${loginId}`);
}

export function answerProviderOAuthLogin(profileId: string, loginId: string, body: Schemas["OAuthAnswerIn"]): Promise<ProviderOAuthLogin> {
  return api<ProviderOAuthLogin>(`/api/settings/providers/${profileId}/oauth/login/${loginId}/answer`, json("POST", body));
}

export function cancelProviderOAuthLogin(profileId: string, loginId: string): Promise<void> {
  return api<void>(`/api/settings/providers/${profileId}/oauth/login/${loginId}`, { method: "DELETE" });
}

/** 退出这条连接上的订阅登录。 */
export function unlinkProviderOAuth(profileId: string): Promise<ProviderProfile> {
  return api<ProviderProfile>(`/api/settings/providers/${profileId}/oauth`, { method: "DELETE" });
}

// ── 模型行 ────────────────────────────────────────────────────────────────────

export function listProviderModels(profileId: string): Promise<ProviderModel[]> {
  return api<ProviderModel[]>(`/api/settings/providers/${profileId}/models`);
}

export function addProviderModel(profileId: string, body: Schemas["ProviderModelUpdate"]): Promise<ProviderModel> {
  return api<ProviderModel>(`/api/settings/providers/${profileId}/models`, json("POST", body));
}

export function updateProviderModel(profileId: string, modelId: string, body: Schemas["ProviderModelUpdate"]): Promise<ProviderModel> {
  return api<ProviderModel>(`/api/settings/providers/${profileId}/models/${segment(modelId)}`, json("PATCH", body));
}

export function deleteProviderModel(profileId: string, modelId: string): Promise<void> {
  return api<void>(`/api/settings/providers/${profileId}/models/${segment(modelId)}`, { method: "DELETE" });
}

// ── 能力默认 ──────────────────────────────────────────────────────────────────

/** 某个能力下可选的模型(跨我所有的连接)。 */
export function listCapabilityModels(capability: string, surface: ModelSurface = "all"): Promise<CapabilityModel[]> {
  return api<CapabilityModel[]>(`/api/settings/capability-models/${capability}?surface=${surface}`);
}

/** 我自己的每项能力默认用哪个模型。 */
export function listProviderDefaults(): Promise<ProviderDefault[]> {
  return api<ProviderDefault[]>("/api/settings/provider-defaults");
}

export function setProviderDefault(capability: string, body: Schemas["ProviderDefaultUpdate"]): Promise<ProviderDefault> {
  return api<ProviderDefault>(`/api/settings/provider-defaults/${capability}`, json("PUT", body));
}

// ── 生成参数组(用户给自己那条连接写的参数描述) ─────────────────────────────────

export function listGenerationProfiles(profileId: string, kind: string): Promise<GenerationProfile[]> {
  return api<GenerationProfile[]>(`/api/settings/providers/${profileId}/generation-profiles?kind=${segment(kind)}`);
}

export function createGenerationProfile(profileId: string, body: Schemas["GenerationCapabilityProfileCreate"]): Promise<GenerationProfile> {
  return api<GenerationProfile>(`/api/settings/providers/${profileId}/generation-profiles`, json("POST", body));
}

export function updateGenerationProfile(
  profileId: string,
  refId: string,
  body: Schemas["GenerationCapabilityProfileUpdate"],
): Promise<GenerationProfile> {
  return api<GenerationProfile>(`/api/settings/providers/${profileId}/generation-profiles/${refId}`, json("PATCH", body));
}

export function deleteGenerationProfile(profileId: string, refId: string): Promise<void> {
  return api<void>(`/api/settings/providers/${profileId}/generation-profiles/${refId}`, { method: "DELETE" });
}

// ── 计价规则 ──────────────────────────────────────────────────────────────────

export function listPricingRules(workspaceId: string): Promise<PricingRule[]> {
  return api<PricingRule[]>(`/api/settings/provider-pricing-rules?workspace_id=${segment(workspaceId)}`);
}

export function createPricingRule(body: Schemas["ProviderPricingRuleCreate"]): Promise<PricingRule> {
  return api<PricingRule>("/api/settings/provider-pricing-rules", json("POST", body));
}

export function updatePricingRule(ruleId: string, body: Schemas["ProviderPricingRuleUpdate"]): Promise<PricingRule> {
  return api<PricingRule>(`/api/settings/provider-pricing-rules/${ruleId}`, json("PATCH", body));
}

export function deletePricingRule(ruleId: string): Promise<void> {
  return api<void>(`/api/settings/provider-pricing-rules/${ruleId}`, { method: "DELETE" });
}

/** 按内置价目表给这条连接的模型预填计价规则。 */
export function prefillPricingRules(profileId: string): Promise<PricingPrefill> {
  return api<PricingPrefill>(`/api/settings/providers/${profileId}/pricing/prefill`, { method: "POST" });
}
