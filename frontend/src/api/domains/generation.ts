import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type GenerationOption = components["schemas"]["GenerationOptionOut"];
export type GenerationJob = components["schemas"]["GenerationJobOut"];
export type GenerationCreateResponse = components["schemas"]["GenerationCreateResponse"];

/** A model exposed by one provider profile. Unknown limits remain null, never guessed. */
/** 这里只要这几栏 —— 用 `Pick` 而不是手写一个同形的 interface:少写一栏是**有意收窄**,
 *  而手写那份在后端改名/删字段时不会有任何反应。 */
export type ProviderModel = Pick<components["schemas"]["ProviderModelOut"], "id" | "context_window" | "max_output_tokens">;

export type PromptOptimizeResult = components["schemas"]["PromptOptimizeResponse"];

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
