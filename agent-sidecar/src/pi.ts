/**
 * pi integration (S2): build an OpenAI-compatible provider from the config
 * Mibu passes per turn (base URL + key + model), then run a turn through pi's
 * Agent and stream text deltas back out. Tools/hooks come in S3+.
 */
import { Agent } from "@earendil-works/pi-agent-core";
import { createModels, createProvider, type Model, type Models } from "@earendil-works/pi-ai";
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";

const PROVIDER_ID = "mibu";

/** A single-provider Models collection targeting an OpenAI-compatible endpoint. */
function buildModels(baseUrl: string, apiKey: string, modelId: string): { models: Models; model: Model<"openai-completions"> } {
  const model: Model<"openai-completions"> = {
    id: modelId,
    name: modelId,
    api: "openai-completions",
    provider: PROVIDER_ID,
    baseUrl,
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 128000,
    maxTokens: 8000,
    // Ollama / vLLM / LM Studio 等本地 OpenAI 兼容服务不认 developer role 与 reasoning_effort
    compat: { supportsDeveloperRole: false, supportsReasoningEffort: false },
  };
  const provider = createProvider({
    id: PROVIDER_ID,
    name: "Mibu provider",
    baseUrl,
    // keyless 本地服务返回空 auth;有 key 的走 apiKey
    auth: { apiKey: { name: "Mibu provider key", resolve: async () => (apiKey ? { auth: { apiKey } } : { auth: {} }) } },
    models: [model],
    api: openAICompletionsApi(),
  });
  const models = createModels();
  models.setProvider(provider);
  return { models, model };
}

export interface PiTurnInput {
  systemPrompt: string;
  prompt: string;
  provider: { baseUrl: string; apiKey: string };
  model: string;
}

/** Run one turn through pi's Agent; emit each text delta, return the full text. */
export async function runPiTurn(input: PiTurnInput, onDelta: (delta: string) => void): Promise<string> {
  const { models, model } = buildModels(input.provider.baseUrl, input.provider.apiKey, input.model);
  const agent = new Agent({
    initialState: { systemPrompt: input.systemPrompt, model },
    streamFn: (m, context, options) => models.stream(m, context, options),
  });
  let full = "";
  agent.subscribe((event) => {
    if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
      const delta = event.assistantMessageEvent.delta;
      full += delta;
      onDelta(delta);
    }
  });
  await agent.prompt(input.prompt);
  return full;
}
