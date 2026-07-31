/**
 * pi integration (S2): build an OpenAI-compatible provider from the config
 * Open Studio passes per turn (base URL + key + model), then run a turn through pi's
 * Agent and stream text deltas back out. Tools/hooks come in S3+.
 */
import { Agent, type AgentMessage, type AgentTool } from "@earendil-works/pi-agent-core";
import {
  createModels,
  createProvider,
  type Api,
  type Credential,
  type CredentialStore,
  type Model,
  type Models,
  type Provider,
} from "@earendil-works/pi-ai";

import { BackendCredentialStore } from "./credentials.js";
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

/** 端点没告诉我们上下文窗口时的回退。
 *
 * 取**小**值是刻意的:这个数只用于 pi 决定何时压缩上下文,估大了会把超窗的请求原样发出去,
 * 由服务端拒掉(用户看到的是一次失败的对话);估小了只是压缩得早一点。以前这里硬编 128000,
 * 配 8k 上下文的本地模型时就是前一种。真实值现在由后端从供应商 /models 目录取。 */
const FALLBACK_CONTEXT_WINDOW = 32000;
const FALLBACK_MAX_TOKENS = 4096;

/** A single-provider Models collection targeting an OpenAI-compatible endpoint. */
function buildModels(
  baseUrl: string,
  apiKey: string,
  modelId: string,
  limits: { contextWindow?: number | null; maxOutputTokens?: number | null } = {},
): { models: Models; model: Model<"openai-completions"> } {
  const model: Model<"openai-completions"> = {
    id: modelId,
    name: modelId,
    api: "openai-completions",
    provider: PROVIDER_ID,
    baseUrl,
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: limits.contextWindow ?? FALLBACK_CONTEXT_WINDOW,
    maxTokens: limits.maxOutputTokens ?? FALLBACK_MAX_TOKENS,
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

/** 订阅计划:vendor id → pi 内置的 Provider 工厂。
 *
 * **这里刻意只有一张映射表**。端点、模型目录(含真实 contextWindow)、设备码 / PKCE 授权流程
 * 全在 pi 自己的 Provider 定义里,我们一个字段都不重描:各家差异极大(Copilot 的 endpoint
 * 随凭据变,Codex 走自己的 responses API),照抄进来就等于把六家协议维护在这边,上游一改就
 * 悄悄失效。后端 VENDOR_PRESETS 里的 `pi_provider` 就是这张表的键。
 */
const SUBSCRIPTION_PROVIDERS: Record<string, () => Promise<Provider>> = {
  anthropic: async () => (await import("@earendil-works/pi-ai/providers/anthropic")).anthropicProvider(),
  "kimi-coding": async () => (await import("@earendil-works/pi-ai/providers/kimi-coding")).kimiCodingProvider(),
  "openai-codex": async () => (await import("@earendil-works/pi-ai/providers/openai-codex")).openaiCodexProvider(),
  "github-copilot": async () =>
    (await import("@earendil-works/pi-ai/providers/github-copilot")).githubCopilotProvider(),
  xai: async () => (await import("@earendil-works/pi-ai/providers/xai")).xaiProvider(),
  openrouter: async () => (await import("@earendil-works/pi-ai/providers/openrouter")).openrouterProvider(),
};

export function isSubscriptionProvider(piProvider: string): boolean {
  return Boolean(SUBSCRIPTION_PROVIDERS[piProvider]);
}

/** 订阅计划的 Models:用 pi 现成的 Provider + 后端托管的凭据存储。
 *
 * modelId 省略时不解析模型(登录流程只需要装好 provider 的 Models)。 */
export async function buildSubscriptionModels(
  piProvider: string,
  modelId: string | undefined,
  credentials: CredentialStore,
): Promise<{ models: Models; model: Model<Api> | undefined; provider: Provider }> {
  const factory = SUBSCRIPTION_PROVIDERS[piProvider];
  if (!factory) throw new Error(`未知的订阅供应商:${piProvider}`);
  const provider = await factory();
  const models = createModels({ credentials });
  models.setProvider(provider);
  if (modelId === undefined) return { models, model: undefined, provider };
  // 目录里没有这个 id 时不猜:报出来比拿一个别的模型悄悄跑掉好。
  const model = models.getModel(provider.id, modelId);
  if (!model) {
    const known = provider
      .getModels()
      .slice(0, 8)
      .map((m) => m.id)
      .join("、");
    throw new Error(`供应商「${provider.name}」没有模型 ${modelId};可用的有:${known}…`);
  }
  return { models, model, provider };
}

export interface PiTurnInput {
  systemPrompt: string;
  prompt: string;
  provider: {
    baseUrl: string;
    apiKey: string;
    contextWindow?: number | null;
    maxOutputTokens?: number | null;
    /** 非空 = 订阅计划,用 pi 现成的 Provider(见 SUBSCRIPTION_PROVIDERS)。 */
    piProvider?: string;
    /** 订阅计划的当前凭据(pi 的 Credential 原样),随帧发下来省一次网络往返。 */
    credential?: Credential | null;
    /** 凭据写回后端时用;订阅计划必填。 */
    profileId?: string;
  };
  model: string;
  tools: AgentTool[];
  /** 回连 Open Studio 的地址与凭证 —— 订阅计划刷新令牌时要写回后端。 */
  apiBase: string;
  token: string;
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
  const piProvider = input.provider.piProvider ?? "";
  const { models, model } = piProvider
    ? await buildSubscriptionModels(
        piProvider,
        input.model,
        new BackendCredentialStore(
          input.apiBase,
          input.token,
          input.provider.profileId ?? "",
          input.provider.credential ?? undefined,
        ),
      )
    : buildModels(input.provider.baseUrl, input.provider.apiKey, input.model, input.provider);
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
