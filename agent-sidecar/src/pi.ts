/**
 * pi integration (S2): build an OpenAI-compatible provider from the config
 * Open Studio passes per turn (base URL + key + model), then run a turn through pi's
 * Agent and stream text deltas back out. Tools/hooks come in S3+.
 */
import { Agent, type AgentMessage, type AgentTool } from "@earendil-works/pi-agent-core";
import { createModels, createProvider, type Model, type Models } from "@earendil-works/pi-ai";
// 规范入口(不是 `/compat` —— 那是上游标注为「临时、将随 ModelManager 迁移删除」的兼容层)。
// 这个入口能用的前提是构建带 --ignore-annotations,原因见 package.json 里的说明。
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";

const PROVIDER_ID = "open-studio";

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
    name: "Open Studio provider",
    baseUrl,
    // 本地服务(Ollama/LM Studio 等)通常不需要 key,但 pi 缺少 apiKey 时会直接报
    // "No API key for provider" —— 所以补一个占位值,这类端点会忽略它。
    auth: {
      apiKey: {
        name: "Open Studio provider key",
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
  usage: Record<string, unknown>;
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
  return {
    text: full,
    usage: collectUsage(messages),
    sessionState: messages,
    errorMessage: aborted ? undefined : failed?.errorMessage,
    aborted,
  };
}

/**
 * 把本轮真实的 token 用量汇总出来。
 *
 * 以前这里只回 `{ requests: 1 }`,一个 token 数都没有 —— 于是后端的 `_turn_metering` 走兜底分支,
 * **按字符数估算**并打上 `token_estimate: true`。也就是说用量图表与费用统计一直是估算值,
 * 而 pi 本来就在每条助手消息上带着供应商回报的真实数字。
 *
 * 一轮可能有多条助手消息(工具调用会触发后续 LLM 调用),所以要累加而不是取最后一条。
 * 字段名对齐后端 `_turn_metering` 认的那组(input_tokens / output_tokens / total_tokens),
 * 认到了就不会再估算。cacheRead/cacheWrite 另记:它们计价不同,压平进 input 会让费用偏高。
 */
function collectUsage(messages: readonly unknown[]): Record<string, number> {
  let input = 0, output = 0, cacheRead = 0, cacheWrite = 0, reasoning = 0, requests = 0;
  for (const message of messages) {
    const usage = (message as { role?: string; usage?: Record<string, number> }).usage;
    if (!usage || (message as { role?: string }).role !== "assistant") continue;
    requests += 1;
    input += usage.input ?? 0;
    output += usage.output ?? 0;
    cacheRead += usage.cacheRead ?? 0;
    cacheWrite += usage.cacheWrite ?? 0;
    reasoning += usage.reasoning ?? 0;
  }
  // 一条都没读到就别硬报 0:那会让后端以为拿到了真实用量而跳过估算,结果是费用恒为 0
  // —— 比估算更糟。宁可退回估算。
  if (requests === 0) return { requests: 1 };
  const out: Record<string, number> = {
    requests,
    input_tokens: input,
    output_tokens: output,
    total_tokens: input + output,
  };
  if (cacheRead) out.cache_read_tokens = cacheRead;
  if (cacheWrite) out.cache_write_tokens = cacheWrite;
  if (reasoning) out.reasoning_tokens = reasoning;
  return out;
}
