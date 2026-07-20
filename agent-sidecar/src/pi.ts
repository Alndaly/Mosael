/**
 * pi integration (S2): build an OpenAI-compatible provider from the config
 * Mibu passes per turn (base URL + key + model), then run a turn through pi's
 * Agent and stream text deltas back out. Tools/hooks come in S3+.
 */
import { Agent, type AgentMessage, type AgentTool } from "@earendil-works/pi-agent-core";
import { createModels, createProvider, type Model, type Models } from "@earendil-works/pi-ai";
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";

const PROVIDER_ID = "mibu";

// 上下文压缩(S7):超过阈值时只把最近若干条喂给 LLM,避免长对话撑爆上下文窗口。
// 切点回退到最近的一条 user 消息,保证不切断 assistant 工具调用与其 toolResult 的配对。
const COMPACT_OVER = 40;
const COMPACT_KEEP = 24;

function compactContext(messages: AgentMessage[]): AgentMessage[] {
  if (messages.length <= COMPACT_OVER) return messages;
  let start = messages.length - COMPACT_KEEP;
  while (start > 0 && (messages[start] as { role?: string }).role !== "user") start -= 1;
  return start > 0 ? messages.slice(start) : messages;
}

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
    // 本地服务(Ollama/LM Studio 等)通常不需要 key,但 pi 缺少 apiKey 时会直接报
    // "No API key for provider" —— 所以补一个占位值,这类端点会忽略它。
    auth: {
      apiKey: {
        name: "Mibu provider key",
        resolve: async () => ({ auth: { apiKey: apiKey || "not-required" } }),
      },
    },
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
  tools: AgentTool[];
  /** pi 上轮序列化的消息数组(多轮记忆);首轮为空。 */
  sessionState?: unknown;
  /** Called with the Agent once built, so the caller can steer or abort the running turn. */
  onAgentReady?: (agent: Agent) => void;
}

export interface PiTurnResult {
  text: string;
  /** 本轮结束后的完整消息数组,回存给下一轮。 */
  sessionState: AgentMessage[];
  /**
   * 模型调用失败时 pi **不抛异常** —— 它把失败记在最后一条 assistant 消息上
   * (stopReason:"error" + errorMessage),照常结束这一轮。不主动挖出来的话,
   * 上游只会看到一个空的 turn_done,配置错误就变成了"什么都没发生"。
   */
  errorMessage?: string;
  /** True when the run was stopped by abort() rather than finishing on its own. */
  aborted?: boolean;
}

export interface PiTurnHandlers {
  onDelta: (delta: string) => void;
  onToolStart: (toolCallId: string, name: string, args: unknown) => void;
  onToolEnd: (toolCallId: string, result: unknown, isError: boolean) => void;
}

/** Run one turn through pi's Agent; stream text + tool events, return text + new state. */
export async function runPiTurn(input: PiTurnInput, handlers: PiTurnHandlers): Promise<PiTurnResult> {
  const { models, model } = buildModels(input.provider.baseUrl, input.provider.apiKey, input.model);
  const priorMessages = Array.isArray(input.sessionState) ? (input.sessionState as AgentMessage[]) : [];
  const agent = new Agent({
    initialState: { systemPrompt: input.systemPrompt, model, tools: input.tools, messages: priorMessages },
    streamFn: (m, context, options) => models.stream(m, context, options),
    // 每次 LLM 调用前压缩上下文;state.messages 保留全量(多轮记忆不受影响)
    transformContext: async (messages) => compactContext(messages),
  });
  // One queued message per turn, in the order they were sent. Draining the whole queue at
  // once merges several questions into a single answer, which reads as the agent ignoring
  // all but the last — a queue the user can see the order of has to be answered in that order.
  agent.steeringMode = "one-at-a-time";
  agent.followUpMode = "one-at-a-time";
  input.onAgentReady?.(agent);

  let full = "";
  agent.subscribe((event) => {
    if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
      const delta = event.assistantMessageEvent.delta;
      full += delta;
      handlers.onDelta(delta);
    } else if (event.type === "tool_execution_start") {
      handlers.onToolStart(event.toolCallId, event.toolName, event.args);
    } else if (event.type === "tool_execution_end") {
      handlers.onToolEnd(event.toolCallId, event.result, event.isError);
    }
  });
  let aborted = false;
  try {
    await agent.prompt(input.prompt);
  } catch (err) {
    // An aborted run rejects. The text streamed so far is real output the user watched
    // arrive, so it is returned rather than discarded.
    if (agent.signal?.aborted || String(err).includes("abort")) aborted = true;
    else throw err;
  }
  const messages = agent.state.messages;
  // 最近一条标记为 error 的消息即本轮的失败原因(如 base_url 不是 OpenAI 兼容端点、
  // 模型不存在、鉴权失败)。
  const failed = [...messages]
    .reverse()
    .find((message) => (message as { stopReason?: string }).stopReason === "error") as
    | { errorMessage?: string }
    | undefined;
  return { text: full, sessionState: messages, errorMessage: aborted ? undefined : failed?.errorMessage, aborted };
}
