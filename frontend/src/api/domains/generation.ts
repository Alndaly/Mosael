import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type GenerationOption = components["schemas"]["GenerationOptionOut"];
export type GenerationJob = components["schemas"]["GenerationJobOut"];
export type GenerationCreateResponse = components["schemas"]["GenerationCreateResponse"];
export type PluginPackage = components["schemas"]["PluginPackageOut"];
export type PluginInstance = components["schemas"]["PluginInstanceOut"];
export type PluginField = components["schemas"]["PluginFieldOut"];
export type PluginToolState = components["schemas"]["PluginToolStateOut"];
export type PluginTool = components["schemas"]["PluginToolOut"];
export type PluginInvocation = components["schemas"]["PluginInvocationOut"];
export type PluginPermissionGrant = components["schemas"]["PluginPermissionGrantOut"];
export type PluginCredential = components["schemas"]["PluginCredentialOut"];

/** A model exposed by one provider profile. Unknown limits remain null, never guessed. */
export interface ProviderModel {
  id: string;
  context_window: number | null;
  max_output_tokens: number | null;
}

export interface PromptOptimizeResult {
  prompt: string;
  negative_prompt: string;
  notes: string;
  platform: string;
}

export interface ComfyWorkflow {
  path: string;
  name: string;
  modified: number | null;
}

export interface ComfyParam {
  node_id: string;
  class_type: string;
  title: string | null;
  name: string;
  value: unknown;
  role: "prompt" | "negative" | "seed" | "width" | "height" | null;
  type: "INT" | "FLOAT" | "STRING" | "COMBO" | "BOOLEAN";
  options?: string[];
  min?: number;
  max?: number;
  step?: number;
  multiline?: boolean;
}

export function listProviderModels(profileId: string): Promise<ProviderModel[]> {
  return api<ProviderModel[]>(`/api/settings/providers/${profileId}/models`);
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

export function listComfyuiWorkflows(profileId?: string): Promise<ComfyWorkflow[]> {
  const query = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : "";
  return api<ComfyWorkflow[]>(`/api/generation/comfyui/workflows${query}`);
}

export function listComfyuiWorkflowParams(workflow: string, profileId?: string): Promise<ComfyParam[]> {
  const query = new URLSearchParams({ workflow });
  if (profileId) query.set("profile_id", profileId);
  return api<ComfyParam[]>(`/api/generation/comfyui/workflow-params?${query.toString()}`);
}
