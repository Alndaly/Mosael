import { describe, expect, it } from "vitest";

import type { components } from "@/api/generated/schema";
import { generationModelSuggestions } from "@/features/settings/ProviderDefaultsSection";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type GenerationModel = components["schemas"]["GenerationModelOut"];

const profile = (patch: Partial<ProviderProfile>): ProviderProfile =>
  ({
    id: "provider-1",
    name: "Custom endpoint",
    vendor: "openai-compatible",
    base_url: "https://example.test/v1",
    default_model: "",
    enabled: true,
    created_at: "2026-07-21T00:00:00Z",
    key_hint: "",
    extra: {},
    ...patch,
  }) as ProviderProfile;

const model = (patch: Partial<GenerationModel>): GenerationModel =>
  ({
    id: "openai:gpt-image-2:image",
    provider: "openai",
    kind: "image",
    model: "gpt-image-2",
    enabled: true,
    capabilities: {},
    adapter_available: true,
    ...patch,
  }) as GenerationModel;

describe("generationModelSuggestions", () => {
  it("keeps a custom OpenAI-compatible provider's default model even when the built-in catalog uses openai", () => {
    const suggestions = generationModelSuggestions(
      profile({ default_model: "gpt-image-2" }),
      [model({ provider: "openai", model: "gpt-image-2" })],
      "",
    );

    expect(suggestions).toEqual(["gpt-image-2"]);
  });

  it("keeps an already saved custom model as the first suggestion", () => {
    const suggestions = generationModelSuggestions(
      profile({ default_model: "gpt-image-2" }),
      [model({ provider: "openai-compatible", model: "another-image-model" })],
      "my-custom-image-model",
    );

    expect(suggestions).toEqual(["my-custom-image-model", "gpt-image-2", "another-image-model"]);
  });
});
