/**
 * pi integration (S2): build an OpenAI-compatible provider from the config
 * Mosael passes per turn (base URL + key + model), then run a turn through pi's
 * Agent and stream text deltas back out. Tools/hooks come in S3+.
 */
import { Agent, type AgentMessage, type AgentTool } from "@earendil-works/pi-agent-core";
import {
  createModels,
  createProvider,
  type Api,
  type Credential,
  type CredentialStore,
  type ImageContent,
  type Context,
  type Model,
  type Models,
  type Provider,
} from "@earendil-works/pi-ai";

import { BackendCredentialStore } from "./credentials.js";
import type { RunTurnRequest } from "./protocol.js";
import { dropToolImages, keepRecentToolImages } from "./toolImages.js";
// 规范入口(不是 `/compat` —— 那是上游标注为「临时、将随 ModelManager 迁移删除」的兼容层)。
// 这个入口能用的前提是构建带 --ignore-annotations,原因见 package.json 里的说明。
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";

import { estimateContextTokens } from "@earendil-works/pi-ai/utils/estimate";

import {
  type CompactionResult,
  type Message as CompactionMessage,
  SUMMARY_PROMPT,
  compact,
  dropOlder,
  FALLBACK_CONTEXT_WINDOW,
  fallbackContextWindow,
  contextTokens,
  fitTurnContext,
} from "./compaction";
import {
  SubagentManager,
  readOnlyTools,
  runSubagent,
  subagentToolSpec,
  waitSubagentsToolSpec,
  type SubagentOutcome,
  type SubagentToolEvent,
} from "./subagent.js";

const PROVIDER_ID = "mosael";

/** 主智能体手里的 run_subagent。子智能体只拿只读工具(理由见 subagent.ts),
 *  它的每一步都当作父工具卡的进度上报 —— 否则界面上是一段几十秒的静默。 */
function buildSubagentTools(
  allTools: AgentTool[],
  model: Model<Api>,
  streamFn: unknown,
  handlers: PiTurnHandlers,
  manager: SubagentManager,
): AgentTool[] {
  const spec = subagentToolSpec();
  const waitSpec = waitSubagentsToolSpec();
  const archiveOf = (task: string, outcome: SubagentOutcome) => ({
    task,
    steps: outcome.steps,
    error: outcome.error ?? null,
    trace: outcome.trace,
  });
  const dispatchTool: AgentTool = {
    name: spec.name,
    label: "子智能体",
    description: spec.description,
    parameters: spec.parameters as never,
    execute: async (parentCallId: string, rawParams: unknown, signal?: AbortSignal) => {
      const args = (rawParams ?? {}) as { task?: string; expected_output?: string; wait?: boolean };
      const task = (args.task ?? "").trim();
      if (!task) throw new Error("task 不能为空");
      const prompt = args.expected_output ? `${task}\n\n【期望的输出形式】${args.expected_output}` : task;
      const running = runSubagent({
        task: prompt,
        tools: readOnlyTools(allTools),
        model,
        streamFn,
        signal,
        // 每一步实时外发,挂在**这次 run_subagent 调用**名下 —— 界面据此把子步
        // 归到发起它的那张卡,而不是一段几十秒的静默。
        onToolEvent: (event: SubagentToolEvent) => handlers.onSubtool?.({ parentCallId, ...event }),
      });
      if (args.wait === true) {
        // 阻塞路径:等到报告直接返回 —— 模型明说"这一个不等到没法继续"。
        const result = await running;
        const payload = result.error
          ? { ok: false, error: result.error, steps: result.steps }
          : { ok: true, report: result.report, steps: result.steps };
        // 完整轨迹只进 details(UI 存档),**不进 content** —— content 会回填给主模型,
        // 而省下那份上下文正是派子智能体的意义。task 一起存:列表里靠它认出这是哪个子代理。
        return {
          content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
          details: { data: payload, subagent: archiveOf(task, result) },
        };
      }
      // 默认路径:立即返回,子智能体在后台跑。id 就用这次调用的 toolCallId ——
      // UI 时间线已经拿它当锚,模型拿它来 wait,两边天然对上。
      manager.dispatch(parentCallId, task, running);
      void running.then((outcome) => {
        // 跑完就把存档发给宿主,让界面上这张卡从「进行中」翻成完整档案 ——
        // 不等模型来取:看得见过程是 UI 的事,和模型什么时候读报告无关。
        handlers.onSubagentResult?.(parentCallId, archiveOf(task, outcome));
      });
      const payload = {
        ok: true,
        dispatched: true,
        subagent_id: parentCallId,
        note: "Sub-agent is running in the background. Keep working; call wait_subagents when you need its report, or finish your reply and the report will be delivered to you.",
      };
      return {
        content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
        details: { data: payload, subagent_dispatched: true },
      };
    },
  };
  const waitTool: AgentTool = {
    name: waitSpec.name,
    label: "等待子智能体",
    description: waitSpec.description,
    parameters: waitSpec.parameters as never,
    execute: async (_callId: string, rawParams: unknown) => {
      const args = (rawParams ?? {}) as { subagent_ids?: string[] };
      if (manager.size() === 0) {
        return {
          content: [{ type: "text", text: JSON.stringify({ ok: false, error: "没有在跑的子智能体" }) }],
          details: {},
        };
      }
      const settled = await manager.wait(args.subagent_ids);
      // 报告走 content 进模型上下文 —— wait 的意义就是"把答案拿进来"。
      const payload = settled.map(({ id, outcome }) => ({
        subagent_id: id,
        ok: !outcome.error,
        report: outcome.report || undefined,
        error: outcome.error,
        steps: outcome.steps,
      }));
      return {
        content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
        details: { data: payload },
      };
    },
  };
  return [dispatchTool, waitTool];
}

// 轮内兜底:工具结果是在轮前摘要之后才出现的。除了防连续调用堆出过多消息，还要按 token
// 控制单个超大结果，否则 pi 会把 max_tokens 压到 1，留下「我」这样的碎片。
const RUNAWAY_TURN_MESSAGES = 120;
const RUNAWAY_KEEP = 60;

/** pi 夹 max_tokens 时给上下文估算留的余量(pi-ai api/simple-options 的 CONTEXT_SAFETY_TOKENS,没有导出)。 */
const PI_CONTEXT_SAFETY_TOKENS = 4096;
/**
 * 一次请求至少要留得出这么多输出额度,不够就不发。和 pi 给「思考之后的正文」留的下限同一个数
 * (simple-options 的 MIN_ANSWER_TOKENS):少于它,模型能说出来的就只剩半句话。
 */
const MIN_REPLY_TOKENS = 1024;

/** 窗口装不下这次请求(见 guardRunawayTurn)。单独一类,好让后端把它说成「窗口太小」而不是「检查供应商配置」。 */
class ContextFullError extends Error {}

/**
 * 每次请求前(transformContext)整理发送副本,保证**留得出一段回答**。
 *
 * pi 按「窗口 − 已用 − 4096」夹 max_tokens,下限是 1(clampMaxTokensToContext)。上下文一满就只剩几个 token:
 * 用户看到「我」「抱歉」,或者一句话说到冒号就没了,而这一轮看起来是正常结束的。所以:
 *   1. 消息堆得太多就丢掉早先的(从一条 user 边界起,工具调用和结果不拆开);
 *   2. 按 token 裁超大的工具结果,至少空出四分之一窗口、且不少于 MIN_REPLY_TOKENS 的输出额度;
 *   3. 用 **pi 自己的估算**复核一遍 —— 还是留不出,就不发这个请求,报一句说得清的错。
 *      那种情况是固定开销(工具定义 + 系统提示 + 没法裁的历史)自己就快占满窗口,裁不出来;发出去只会换来半句话。
 */
function guardRunawayTurn(messages: AgentMessage[], contextWindow: number, maxTokens: number): AgentMessage[] {
  let guarded = messages as unknown as CompactionMessage[];
  if (guarded.length > RUNAWAY_TURN_MESSAGES) {
    let start = guarded.length - RUNAWAY_KEEP;
    while (start > 0 && guarded[start]?.role !== "user") start -= 1;
    guarded = dropOlder(guarded, start);
  }
  const need = Math.min(MIN_REPLY_TOKENS, maxTokens);
  const fitted = fitTurnContext(
    guarded,
    Math.min(Math.floor(contextWindow * 0.75), contextWindow - PI_CONTEXT_SAFETY_TOKENS - need),
  ) as unknown as AgentMessage[];
  const used = estimateContextTokens(fitted as unknown as Parameters<typeof estimateContextTokens>[0]).tokens;
  if (contextWindow - used - PI_CONTEXT_SAFETY_TOKENS < need) {
    throw new ContextFullError(
      `上下文窗口放不下这一次请求:窗口 ${contextWindow.toLocaleString("en-US")} Token,要发出去的内容已有约 ` +
        `${used.toLocaleString("en-US")} Token,留给回答的不到 ${need.toLocaleString("en-US")}。请在模型设置里填写这个模型` +
        "真实的上下文窗口(本机推理服务常常比回退值大),或者换一个窗口更大的模型;对话太长的话,先「立即整理」上下文。",
    );
  }
  return fitted;
}

/**
 * 轮前压缩:水位过线就把早期对话交给同一个模型压成交接说明。
 *
 * **放在轮与轮之间而不是 transformContext 里**:后者在一轮内的每次 LLM 调用前都会跑,
 * 工具循环里会被调用很多次 —— 在那儿摘要等于一轮里付好几次摘要的钱,而且每次摘的还是
 * 几乎同一段内容。
 */
async function prepareContext(
  messages: AgentMessage[],
  model: Model<Api>,
  streamFn: ConstructorParameters<typeof Agent>[0]["streamFn"],
  force: boolean,
): Promise<{ messages: AgentMessage[]; info: CompactionResult["info"] }> {
  const contextWindow = Number(model.contextWindow) || 0;
  const result = await compact(messages as unknown as CompactionMessage[], {
    contextWindow,
    force,
    summarize: async (early) => {
      // 摘要用同一个模型:换个便宜模型看着省钱,但它读不懂这段对话里的专有名词和 id,
      // 摘出来的东西反而会误导后续几十轮。工具留空 —— 摘要不该顺手去调工具。
      // 摘要器本身也必须留出输出空间：触发这里的常常正是一个超大的工具结果。
      const summaryInput = fitTurnContext(early, Math.floor(contextWindow * 0.75));
      const summarizer = new Agent({
        initialState: { systemPrompt: "你是一个严谨的对话摘要器。", model, tools: [], messages: summaryInput as unknown as AgentMessage[] },
        streamFn,
      });
      await summarizer.prompt(SUMMARY_PROMPT);
      const last = [...summarizer.state.messages].reverse().find((m) => (m as { role?: string }).role === "assistant");
      const content = (last as { content?: unknown } | undefined)?.content;
      if (typeof content === "string") return content;
      if (Array.isArray(content)) {
        return content
          .map((part) => (typeof part === "string" ? part : String((part as { text?: unknown })?.text ?? "")))
          .join("");
      }
      return "";
    },
  });
  return { messages: result.messages as unknown as AgentMessage[], info: result.info };
}

const FALLBACK_MAX_TOKENS = 4096;
const FALLBACK_REASONING_MAX_TOKENS = 32_768;

/**
 * 目录没有给 maxTokens 时仍要给模型一份够用的输出预算。
 *
 * 对普通兼容端点维持 4K，避免把未知服务直接压垮；只有后端给出了经过验证的思考档位表时，
 * 才按推理模型处理。推理 token 也计入输出额度，4K 很容易全部花在思考上，最后只剩一个字。
 * 同时最多占上下文的四分之一，避免小窗口本地模型没有输入空间。
 */
export function fallbackMaxTokens(
  contextWindow: number,
  thinkingLevelMap?: Record<string, string | null> | null,
): number {
  if (!thinkingLevelMap) return FALLBACK_MAX_TOKENS;
  return Math.max(
    FALLBACK_MAX_TOKENS,
    Math.min(FALLBACK_REASONING_MAX_TOKENS, Math.floor(contextWindow / 4)),
  );
}

/**
 * stopReason=length 是输出预算耗尽，不等于上下文窗口已满。
 *
 * **不看正文长短。** 此前只在正文不到 24 个字(「我」这类碎片)时才报,正文长一点就当成功 —— 而一条停在
 * 「我先看看现在的状态:」的回复同样是被截断的,只是截得体面一些(用户截图:没有工具调用、没有错误,
 * 一轮像是说完了)。截断就是截断。
 */
export function outputLimitMessage(stopReason: string | undefined, text: string, maxTokens: number): string | undefined {
  if (stopReason !== "length") return undefined;
  const budget = `${maxTokens.toLocaleString("en-US")} Token 输出额度（思考过程也计入）`;
  return text.trim().length < 24
    ? `模型已用完本轮 ${budget}，还没来得及形成完整回复。请降低思考强度，或在模型设置中提高「最大输出 Token」后重试。`
    : `回复在本轮 ${budget}处被截断了，已自动让它接着说过一次仍未说完。请降低思考强度，或在模型设置中提高「最大输出 Token」后让它继续。`;
}

/** 一轮**没说完就停下**的原因(给后端的机器可读码)。`context_full`:窗口装不下下一次请求,没有发出去。 */
export type StallCode = "output_limit" | "tool_call_lost" | "paused" | "context_full";

/** `dangling`:正常结束,但停在冒号上 —— 续一次,续完不论怎样都不算错(见 stallOf)。 */
type Stall = { code: Exclude<StallCode, "context_full"> | "dangling"; nudge: string };

/**
 * 这条助手消息是不是「没说完就停下了」—— pi 的循环在下面这几种情况下没有工具可跑,于是安静地结束这一轮:
 *
 *  · stopReason=length 且这条回复里还没有工具调用:输出额度用完了(带了工具调用的那种 pi 自己处理 ——
 *    把截断的调用报成失败结果、让模型重发,循环接着跑);
 *  · stopReason=toolUse(finish_reason=tool_calls)却一个工具调用都没有:模型说要调工具,调用在路上丢了;
 *  · Anthropic 协议的 pause_turn:供应商要我们重发接着来,pi 把它映射成了普通的 stop;
 *  · 正常 stop,但最后一句停在冒号上(`dangling`,见下)。
 *
 * 不是这几种(说完了的 stop、出错、被中止)就是 null。
 */
export function stallOf(message: unknown): Stall | null {
  const m = message as { role?: string; stopReason?: string; rawStopReason?: string; content?: unknown } | undefined;
  if (!m || m.role !== "assistant") return null;
  const hasToolCall = Array.isArray(m.content) && m.content.some((part) => (part as { type?: string })?.type === "toolCall");
  if (m.stopReason === "length" && !hasToolCall) {
    return {
      code: "output_limit",
      nudge:
        "【系统】你上一条回复在输出额度处被截断了,还没说完。请从断处直接接着说下去,不要重复已经说过的内容;如果接下来要调用工具,请完整地发起调用。",
    };
  }
  if (m.stopReason === "toolUse" && !hasToolCall) {
    return {
      code: "tool_call_lost",
      nudge: "【系统】你上一条回复表示要调用工具,但这次没有收到任何工具调用(可能在传输中丢失)。请重新完整地发起你要做的工具调用。",
    };
  }
  if (m.rawStopReason === "pause_turn") {
    return { code: "paused", nudge: "【系统】上一条回复被供应商暂停了(pause_turn)。请从断处接着完成。" };
  }
  // 供应商说正常结束,而最后一句停在冒号上,也没有工具调用。用户截图里连着三轮都是这样:「需要你帮一个小忙:」
  // 「…画板列表是否恢复了:」「没卡住,马上检查现状:」—— 一句话停在冒号上几乎从来不是说完了(多半是接着要调工具
  // 或列内容)。续一次;续完还这样就是模型的决定,不报错。
  if (m.stopReason === "stop" && !hasToolCall && /[:：]\s*$/.test(textOf(m.content))) {
    return {
      code: "dangling",
      nudge:
        "【系统】你上一条回复停在了冒号上,后面没有内容,也没有调用工具。如果接下来要调用工具,现在就完整地发起调用;如果要列出内容或向用户提问,把它说完整。",
    };
  }
  return null;
}

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((part) => (part as { type?: string })?.type === "text")
    .map((part) => String((part as { text?: unknown }).text ?? ""))
    .join("");
}

/** 续过一次之后仍然没说完时,对话里那一行写什么。 */
function stallMessage(stall: Stall & { code: Exclude<Stall["code"], "dangling"> }, text: string, maxTokens: number): string {
  if (stall.code === "output_limit") return outputLimitMessage("length", text, maxTokens) ?? "";
  if (stall.code === "tool_call_lost") {
    return "模型说要调用工具,但供应商返回的回复里没有任何可执行的工具调用(已让它重发过一次)。可以让它重试;反复出现的话,检查这个供应商 / 模型对工具调用的支持。";
  }
  return "供应商暂停了这一轮(pause_turn),已让它接着做过一次仍未完成。可以让它继续。";
}

function lastAssistant(messages: readonly unknown[]): unknown {
  return [...messages].reverse().find((message) => (message as { role?: string }).role === "assistant");
}

/**
 * 这一轮是不是被「停止」掐断的。
 *
 * pi 的 Agent 被 abort 时 **prompt() 不抛**:它记下一条 stopReason="aborted" 的消息、照常结束这一次运行 —— 而运行一结束
 * `agent.signal` 就没了(它挂在那次运行上)。所以此前只靠「prompt 抛了、或者 signal 还是 aborted」来认,一次都认不出来:
 * 停止之后照常发 turn_done,后端把一轮「还没出字就被停下」当成「模型什么都没回」,报一句检查供应商配置;
 * 有子智能体在跑的话,收尾那段还会把它们的报告续成**新的一次请求** —— 用户按了停止,供应商照样被调用。
 */
function stoppedByUser(messages: readonly unknown[]): boolean {
  return (lastAssistant(messages) as { stopReason?: string } | undefined)?.stopReason === "aborted";
}

/** A single-provider Models collection targeting an OpenAI-compatible endpoint. */
export function buildModels(
  baseUrl: string,
  apiKey: string,
  modelId: string,
  limits: {
    contextWindow?: number | null;
    maxOutputTokens?: number | null;
    reasoning?: boolean | null;
    /** 档位 → 供应商接受的值。null = 这一档这个模型不支持(pi 据此把它从可选清单里去掉)。 */
    thinkingLevelMap?: Record<string, string | null> | null;
    vision?: boolean | null;
    reasoningEffort?: boolean | null;
    developerRole?: boolean | null;
  } = {},
): { models: Models; model: Model<"openai-completions"> } {
  const contextWindow =
    typeof limits.contextWindow === "number" && limits.contextWindow > 0
      ? limits.contextWindow
      : fallbackContextWindow(baseUrl);
  const model: Model<"openai-completions"> = {
    id: modelId,
    name: modelId,
    api: "openai-completions",
    provider: PROVIDER_ID,
    baseUrl,
    // vision / developerRole / reasoningEffort 三项默认取**最保守**的那一侧,由用户在设置里
    // 按模型放开:多发一个 reasoning_effort 或 developer 角色,不认的端点会直接 400,整轮
    // 对话失败;而少发只是不用上某个增强。
    //
    // **reasoning 例外,默认开**。它在 pi 里不是"能不能发某个参数",而是这个模型的思考
    // **开关总闸**:pi 里每一条"把思考关掉"的分支(deepseek 的 thinking:{type:"disabled"}、
    // qwen 的 enable_thinking:false、openrouter 的 reasoning:{effort:"none"}…)都写着
    // `&& model.reasoning`。关着的话,会话里的思考档位两个方向都发不出去 —— 请求里既没有
    // "要思考"也没有"别思考",供应商按它自己的默认来,于是 DeepSeek 这类混合模型无论开关
    // 都在思考,用户看到的就是那个开关根本没接线。
    //
    // 默认开**不会**把参数发给不认识它的端点:那些分支是按 baseUrl 匹配到具体供应商的
    // (deepseek.com / z.ai / openrouter.ai…),通用 OpenAI 兼容端点走的是最后两条
    // reasoning_effort 分支,而它们额外要求 supportsReasoningEffort —— 那一项仍然默认关。
    reasoning: limits.reasoning ?? true,
    // 某一档发什么值、发不发得出去。**各家不是同一套词**,而猜错一个值就是整轮 400:
    // Kimi k3 只收 low/high/max 且关不掉,OpenAI 的关闭是 reasoning_effort:"none"。
    // 后端按 vendor 给查证过的那几家(见 domain/thinking),其余不给 —— 不给就是今天的行为。
    ...(limits.thinkingLevelMap ? { thinkingLevelMap: limits.thinkingLevelMap } : {}),
    input: limits.vision ? ["text", "image"] : ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow,
    maxTokens:
      typeof limits.maxOutputTokens === "number" && limits.maxOutputTokens > 0
        ? limits.maxOutputTokens
        : fallbackMaxTokens(contextWindow, limits.thinkingLevelMap),
    // Ollama / vLLM / LM Studio 等本地 OpenAI 兼容服务不认 developer role 与 reasoning_effort
    compat: {
      supportsDeveloperRole: limits.developerRole ?? false,
      // **thinkingLevelMap 一旦给了,就蕴含 supportsReasoningEffort。**
      //
      // 上面那段说"通用兼容端点走 reasoning_effort 分支,而它们额外要求 supportsReasoningEffort
      // —— 那一项仍然默认关",那句话本身没错,错在它和 thinkingLevelMap 一起就成了自相矛盾:
      // 后端给出 thinkingLevelMap 的**前提**正是"我们查证过这个模型收 reasoning_effort 的哪几个
      // 值"(见 backend/app/domain/thinking),而这里再默认关一次,等于当场把刚查证的结论否掉。
      //
      // 后果和 1.3.1 修的那个 bug 一模一样,只是换了位置:界面上有档位(档位清单也来自同一张表)、
      // 用户选得了、会话也存下了,而**四个档位发出去的请求逐字节相同**,一个思考参数都没有。
      //
      // 所以只在"我们并不知道这个模型收什么"时才保守:没有 thinkingLevelMap 就维持默认关,
      // 用户仍可在设置里按模型手动放开(显式值优先)。
      supportsReasoningEffort: limits.reasoningEffort ?? Boolean(limits.thinkingLevelMap),
    },
  };
  const provider = createProvider({
    id: PROVIDER_ID,
    name: "Mosael provider",
    baseUrl,
    // 本地服务(Ollama/LM Studio 等)通常不需要 key,但 pi 缺少 apiKey 时会直接报
    // "No API key for provider" —— 所以补一个占位值,这类端点会忽略它。
    auth: {
      apiKey: {
        name: "Mosael provider key",
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

/**
 * 只刷新凭据,不做任何模型调用。
 *
 * 自动刷新原本只发生在对话路径上 —— pi 在解析模型鉴权时按 expires 判断并调各家的 refresh
 * flow。于是"很久没聊天"之后,额度查询这类旁路一律撞 401,而档案上明明写着已授权。
 *
 * `models.getAuth` 就是 pi 对外的那个口子:返回前会刷新 OAuth,新凭据经我们的
 * CredentialStore(租约互斥)写回后端。所以这里不重描任何一家的刷新协议 —— 那正是当初把
 * 订阅制交给 pi 的原因。
 */
export async function refreshCredential(input: {
  piProvider: string;
  profileId: string;
  credential?: Credential | null;
  apiBase: string;
  token: string;
}): Promise<{ refreshed: boolean }> {
  const { models, provider } = await buildSubscriptionModels(
    input.piProvider,
    undefined,
    new BackendCredentialStore(input.apiBase, input.token, input.profileId, input.credential ?? undefined),
  );
  // 拿不到 auth 说明这个档案根本没登录过,不是"刷新失败" —— 交给调用方去说。
  const auth = await models.getAuth(provider.id);
  return { refreshed: Boolean(auth) };
}

/** 只压缩不对话:走和轮前压缩同一条路径,force=true。 */
export async function runCompaction(input: {
  provider: PiTurnInput["provider"];
  model: string;
  sessionState?: unknown;
  apiBase: string;
  token: string;
}): Promise<{ sessionState: unknown; context: { tokens: number; window: number }; compaction: CompactionResult["info"] }> {
  const piProvider = input.provider.piProvider ?? "";
  const { models, model } = piProvider
    ? await buildSubscriptionModels(
        piProvider,
        input.model,
        new BackendCredentialStore(input.apiBase, input.token, input.provider.profileId ?? "", input.provider.credential ?? undefined),
      )
    : buildModels(input.provider.baseUrl, input.provider.apiKey, input.model, input.provider);
  const prior = Array.isArray(input.sessionState) ? (input.sessionState as AgentMessage[]) : [];
  // **必须是 streamSimple**,不是 stream。pi 的 Agent 把思考档位放在 options.reasoning 里,
  // 而拼请求体的地方读的是 options.reasoningEffort —— 这两者之间的翻译(含按模型 clamp)
  // 只发生在 streamSimple 里。走 stream 的话 reasoningEffort 永远是 undefined,于是供应商
  // 收到的永远是"别思考",思考档位调什么都没用。pi 的 StreamFn 契约原文就写着
  // "Models.streamSimple satisfies this shape",我照着 stream 写才踩进去。
  const streamFn = (
    m: Parameters<typeof models.streamSimple>[0],
    context: Parameters<typeof models.streamSimple>[1],
    options: Parameters<typeof models.streamSimple>[2],
  ) => models.streamSimple(m, context, options);
  const { messages, info } = await prepareContext(prior, model as Model<Api>, streamFn, true);
  return {
    sessionState: messages,
    context: { tokens: contextTokens(messages as unknown as CompactionMessage[]), window: Number(model?.contextWindow) || 0 },
    compaction: info,
  };
}

export interface PiTurnInput {
  systemPrompt: string;
  prompt: string;
  images?: ImageContent[];
  /** 直接复用传输协议里的供应商声明，避免新增能力字段时桥两侧再次漂移。 */
  provider: NonNullable<RunTurnRequest["provider"]>;
  model: string;
  tools: AgentTool[];
  /** 回连 Mosael 的地址与凭证 —— 订阅计划刷新令牌时要写回后端。 */
  apiBase: string;
  token: string;
  /** pi 上轮序列化的消息数组(多轮记忆);首轮为空。 */
  sessionState?: unknown;
  /** Called with the Agent once built, so the caller can steer or abort the running turn. */
  onAgentReady?: (agent: Agent) => void;
  /** 跳过水位判断直接压缩一次 —— 对应界面上的「立即压缩」。 */
  forceCompact?: boolean;
  /** 思考档位。off 时 pi 根本不向供应商要思考(reasoning 传 undefined),
   *  所以"模型是推理模型"和"这一轮要不要思考"是两件事,前者只决定怎么解析。 */
  thinkingLevel?: "off" | "low" | "medium" | "high";
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
  errorCode?: StallCode;
  /** True when the run was stopped by abort() rather than finishing on its own. */
  aborted?: boolean;
  /** 本轮结束时的上下文水位(前端画进度条)。 */
  context?: { tokens: number; window: number };
  /** 本轮**开始前**是否发生了压缩;没发生为 null。 */
  compaction?: CompactionResult["info"];
}

export interface PiTurnHandlers {
  onDelta: (delta: string) => void;
  /** 思考增量。与正文分开上报 —— 混进 onDelta 会让思考内容被当成回答存进消息正文。 */
  onThinking: (delta: string) => void;
  /** 思考结束。前端据此把「思考中…」收起来。 */
  onThinkingEnd: () => void;
  onToolStart: (toolCallId: string, name: string, args: unknown) => void;
  onToolEnd: (toolCallId: string, result: unknown, isError: boolean) => void;
  /** 子智能体的一步工具调用(start/end),挂在发起它的 run_subagent 调用名下。 */
  onSubtool?: (event: { parentCallId: string } & SubagentToolEvent) => void;
  /** 后台派发的子智能体跑完了:把完整存档交给宿主,填回发起那张卡。 */
  onSubagentResult?: (
    parentCallId: string,
    archive: { task: string; steps: number; error: string | null; trace: unknown[] },
  ) => void;
}

export interface GatewayCompletionInput {
  systemPrompt: string;
  prompt: string;
  images?: ImageContent[];
  provider: PiTurnInput["provider"];
  model: string;
  apiBase: string;
  token: string;
  options?: {
    temperature?: number;
    maxTokens?: number;
    maxRetries?: number;
    timeoutMs?: number;
    samplingParams?: Record<string, unknown>;
  };
}

/** One provider completion with OAuth refresh support, but no Agent, tools, state or subagents. */
export async function runGatewayCompletion(
  input: GatewayCompletionInput,
): Promise<{ text: string; usage: Record<string, unknown> }> {
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
  if (!model) throw new Error(`模型 ${input.model} 不存在`);
  const requestedImages = input.images ?? [];
  if (requestedImages.length > 0 && !model.input?.includes("image")) {
    throw new Error(`模型 ${input.model} 不支持图片输入，无法分析图片或视频帧`);
  }
  const images = requestedImages;
  const context: Context = {
    systemPrompt: input.systemPrompt || undefined,
    tools: [],
    messages: [
      {
        role: "user",
        content: images.length > 0 ? [{ type: "text", text: input.prompt }, ...images] : input.prompt,
        timestamp: Date.now(),
      },
    ],
  };
  const answer = await models.completeSimple(model, context, {
    temperature: input.options?.temperature,
    maxTokens: input.options?.maxTokens,
    maxRetries: input.options?.maxRetries,
    timeoutMs: input.options?.timeoutMs,
    samplingParams: input.options?.samplingParams,
    toolChoice: "none",
  });
  if (answer.stopReason === "error") throw new Error(answer.errorMessage || "模型补全失败");
  const text = answer.content
    .filter((part): part is Extract<(typeof answer.content)[number], { type: "text" }> => part.type === "text")
    .map((part) => part.text)
    .join("");
  return { text, usage: answer.usage as unknown as Record<string, unknown> };
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
  const prior = Array.isArray(input.sessionState) ? (input.sessionState as AgentMessage[]) : [];
  const images = model?.input?.includes("image") ? (input.images ?? []) : [];
  let contextFull = false;
  // **必须是 streamSimple**,不是 stream。pi 的 Agent 把思考档位放在 options.reasoning 里,
  // 而拼请求体的地方读的是 options.reasoningEffort —— 这两者之间的翻译(含按模型 clamp)
  // 只发生在 streamSimple 里。走 stream 的话 reasoningEffort 永远是 undefined,于是供应商
  // 收到的永远是"别思考",思考档位调什么都没用。pi 的 StreamFn 契约原文就写着
  // "Models.streamSimple satisfies this shape",我照着 stream 写才踩进去。
  const streamFn = (
    m: Parameters<typeof models.streamSimple>[0],
    context: Parameters<typeof models.streamSimple>[1],
    options: Parameters<typeof models.streamSimple>[2],
  ) => models.streamSimple(m, context, options);
  // 轮前按 token 水位压缩(超过窗口 80% 触发,或调用方显式要求)。
  const { messages: priorMessages, info: compaction } = await prepareContext(
    prior,
    model as Model<Api>,
    streamFn,
    Boolean(input.forceCompact),
  );
  // 子智能体挂在这里而不是 buildAllTools 里:它要用的 model/streamFn 到这一步才解析出来,
  // 而它跑在同一个进程里(见 subagent.ts —— 另起进程就得把供应商解析整套再传一遍)。
  const subagents = new SubagentManager();
  const tools = [...input.tools, ...buildSubagentTools(input.tools, model as Model<Api>, streamFn, handlers, subagents)];
  const agent = new Agent({
    initialState: {
      systemPrompt:
        images.length > 0
          ? `${input.systemPrompt}\n\n当前消息的图片附件已直接作为视觉输入提供给你。直接观察图片回答，不要再为这些图片调用 analyze_asset。`
          : input.systemPrompt,
      model,
      tools,
      messages: priorMessages,
      thinkingLevel: input.thinkingLevel ?? "off",
    },
    streamFn,
    // 轮内兜底:只防单轮里工具调用把消息堆爆、以及留不出回答的请求,正常对话碰不到。
    transformContext: async (messages) => {
      try {
        return guardRunawayTurn(
          keepRecentToolImages(messages, Boolean(model?.input?.includes("image"))),
          Number(model?.contextWindow) || FALLBACK_CONTEXT_WINDOW,
          Number(model?.maxTokens) || FALLBACK_MAX_TOKENS,
        );
      } catch (err) {
        // pi 只把 message 记在失败消息上,类型丢了 —— 在这里记下是哪一类。
        if (err instanceof ContextFullError) contextFull = true;
        throw err;
      }
    },
  });
  const turnStartIndex = priorMessages.length;
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
    } else if (event.type === "message_update" && event.assistantMessageEvent.type === "thinking_delta") {
      // 思考不进 `full`:那是回答正文,会被落库成助手消息的内容。
      handlers.onThinking(event.assistantMessageEvent.delta);
    } else if (event.type === "message_update" && event.assistantMessageEvent.type === "thinking_end") {
      handlers.onThinkingEnd();
    } else if (event.type === "tool_execution_start") {
      handlers.onToolStart(event.toolCallId, event.toolName, event.args);
    } else if (event.type === "tool_execution_end") {
      handlers.onToolEnd(event.toolCallId, event.result, event.isError);
    }
  });
  let aborted = false;
  // 收尾清算:模型答完了,但后台可能还有子智能体在跑、或报告还没进过它的上下文。
  // 等全部跑完,把没送达的报告作为一条通知消息续一轮 —— 模型消化完(可能因此又派新的,
  // 所以是循环)才算真正结束。丢报告是不可接受的:sidecar 是回合级进程,这轮不送,永远没了。
  const settleSubagents = async () => {
    for (;;) {
      if (agent.signal?.aborted || stoppedByUser(agent.state.messages.slice(turnStartIndex))) {
        // 中止也要等后台子智能体真的停下。它们现在收得到同一个中止信号(见 subagent.ts),
        // 所以这一等是有限的 —— 等的是把在飞的请求收掉,不是等它们跑完。
        // 直接 break 的话 promise 还挂在事件循环里,Node 不退,只能等后端强杀收场。
        // 报告在这条路上确实丢了,**但这是用户按的「停止」**,和正常结束那条路的语义不同。
        await subagents.drain().catch(() => []);
        break;
      }
      const settled = await subagents.drain();
      if (settled.length === 0) break;
      const notice = settled
        .map(({ id, task, outcome }) => {
          const head = `【子智能体完成通知】subagent_id=${id}\n任务:${task.split("\n")[0]}`;
          return outcome.error ? `${head}\n结果:失败 —— ${outcome.error}` : `${head}\n报告:\n${outcome.report}`;
        })
        .join("\n\n");
      await agent.prompt(`${notice}\n\n请基于以上报告继续:该转述的转述,该行动的行动。`);
    }
  };
  try {
    if (images.length > 0) await agent.prompt(input.prompt, images);
    else await agent.prompt(input.prompt);
    await settleSubagents();
    // 没说完就停下的(截断 / 工具调用丢了 / 供应商暂停,见 stallOf):**续一次**,让它从断处接着做。
    // 只续一次:输出额度本身太小的话续多少次都一样,那时该说清楚,而不是替用户一遍遍花钱。
    const stall =
      agent.signal?.aborted || stoppedByUser(agent.state.messages.slice(turnStartIndex))
        ? null
        : stallOf(lastAssistant(agent.state.messages));
    if (stall) {
      await agent.prompt(stall.nudge);
      await settleSubagents();
    }
  } catch (err) {
    // An aborted run rejects. The text streamed so far is real output the user watched
    // arrive, so it is returned rather than discarded.
    if (agent.signal?.aborted || String(err).includes("abort")) aborted = true;
    else throw err;
  }
  if (stoppedByUser(agent.state.messages.slice(turnStartIndex))) aborted = true;
  // 工具截图不进会话状态:下一轮重发上一轮的画面没有意义(见 toolImages.ts)。
  const messages = dropToolImages(agent.state.messages);
  const turnMessages = messages.slice(turnStartIndex);
  // 最近一条标记为 error 的消息即本轮的失败原因(如 base_url 不是 OpenAI 兼容端点、
  // 模型不存在、鉴权失败)。
  const failed = [...turnMessages]
    .reverse()
    .find((message) => (message as { stopReason?: string }).stopReason === "error") as
    | { errorMessage?: string }
    | undefined;
  // 续过一次还是没说完:报出来。对话里一定要有一行说清楚,而不是停在一个冒号上假装说完了。
  // (停在冒号上的那种续过就算,不报 —— 见 stallOf。)
  const leftover = aborted || failed?.errorMessage ? null : stallOf(lastAssistant(turnMessages));
  const stalled = leftover && leftover.code !== "dangling" ? { ...leftover, code: leftover.code } : null;
  const stallText = stalled ? stallMessage(stalled, full, Number(model?.maxTokens) || FALLBACK_MAX_TOKENS) : undefined;
  return {
    text: full,
    usage: collectUsage(messages, turnStartIndex),
    sessionState: messages,
    errorMessage: aborted ? undefined : failed?.errorMessage ?? stallText,
    errorCode: aborted ? undefined : contextFull ? "context_full" : stalled ? stalled.code : undefined,
    aborted,
    // 每轮都回报水位:前端据此画进度条。窗口按**当前模型**给 —— 换个模型上限就变了,
    // 用一个全局常量会在小窗口模型上显示成"还早得很"。
    context: {
      tokens: contextTokens(messages as unknown as CompactionMessage[]),
      window: Number(model?.contextWindow) || 0,
    },
    compaction,
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
function collectUsage(messages: readonly unknown[], startIndex = 0): Record<string, number> {
  let input = 0, output = 0, cacheRead = 0, cacheWrite = 0, reasoning = 0, requests = 0;
  for (const message of messages.slice(startIndex)) {
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
