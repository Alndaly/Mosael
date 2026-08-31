/**
 * Wire protocol between the Python backend and this sidecar.
 *
 * Transport: newline-delimited JSON over stdio. The backend writes one
 * request object per line to our stdin; we write event objects to stdout,
 * one per line. stdout carries ONLY protocol JSON — all human/debug logging
 * goes to stderr (see log()).
 */
import type { Credential } from "@earendil-works/pi-ai";

/** Backend -> sidecar. */
export interface RunTurnRequest {
  type: "run_turn";
  turnId: string;
  prompt: string;
  /** Current-turn images; pi.ts applies them only when the selected model declares image input. */
  images?: Array<{ data: string; mimeType: string }>;
  systemPrompt: string;
  /** Prior turns, already trimmed by the backend (may be empty). */
  history?: Array<{ role: "user" | "assistant"; content: string }>;
  workspaceId: string;
  /** Base URL + bearer token for calling Open Studio's HTTP API from tools (S3+). */
  apiBase: string;
  token: string;
  /** Resolved provider for pi-ai (S2+): OpenAI-compatible endpoint + model. */
  provider?: {
    baseUrl: string;
    apiKey: string;
    vendor: string;
    /** 来自供应商 /models 目录;端点没给就缺省,由 pi.ts 用保守回退。 */
    contextWindow?: number | null;
    maxOutputTokens?: number | null;
    /** 按模型的手动覆盖。没填就是 undefined —— 由 sidecar 保持保守默认,而不是当成 false。 */
    reasoning?: boolean | null;
    vision?: boolean | null;
    reasoningEffort?: boolean | null;
    developerRole?: boolean | null;
    /** 订阅计划:pi 内置 Provider 的 id(端点/模型目录/授权流程都在它里面)。 */
    piProvider?: string;
    /** 订阅计划的当前 OAuth 凭据(pi 的 Credential 原样)。 */
    credential?: Credential | null;
    /** 凭据刷新后写回后端时定位档案。 */
    profileId?: string;
  };
  model?: string;
  /** Opaque pi session/compaction state to resume (S5+). */
  sessionState?: unknown;
  /** 跳过水位判断,本轮开始前先压缩一次(界面上的「立即压缩」)。 */
  forceCompact?: boolean;
  /** 思考档位(off/low/medium/high)。不传即 off —— 不向供应商要思考。 */
  thinkingLevel?: "off" | "low" | "medium" | "high";
}

/**
 * Tool-free, stateless completion for boards/workflows.
 *
 * It reuses pi's provider and OAuth credential machinery, but deliberately does not construct
 * an Agent: callers get one deterministic completion and cannot acquire the agent tool surface.
 */
export interface GatewayCompletionRequest {
  type: "gateway_complete";
  turnId: string;
  systemPrompt: string;
  prompt: string;
  images?: Array<{ data: string; mimeType: string }>;
  provider: NonNullable<RunTurnRequest["provider"]>;
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

/**
 * Inject a message into a turn that is already running.
 *
 * "steer" lands after the current assistant message completes, which is what makes it a
 * correction rather than a second conversation: the model sees it before deciding its next
 * step. "follow_up" waits until the agent would otherwise stop, which is a queued next task.
 * Both are pi's own queues — see Agent.steer / Agent.followUp.
 */
export interface SteerRequest {
  type: "steer";
  turnId: string;
  prompt: string;
  mode?: "steer" | "follow_up";
}

/**
 * Declare the whole steering queue, replacing whatever is pending.
 *
 * pi can clear the queue but not remove one entry from it, and the UI needs per-message
 * cancel. Sending the desired queue rather than a delete makes that possible and is
 * idempotent: the client says what should be pending, not what changed.
 */
export interface QueueRequest {
  type: "queue";
  turnId: string;
  prompts: string[];
}

/** Stop a running turn. Whatever it produced so far is kept. */
export interface AbortRequest {
  type: "abort";
  turnId: string;
}

/** 只压缩,不对话。对应界面上的「立即压缩」—— 用户想主动整理上下文,而不是先发一句话。 */
/** 只刷新凭据。对话之外的旁路(如额度查询)在令牌过期时先走这一步。 */
export interface RefreshCredentialRequest {
  type: "refresh_credential";
  turnId: string;
  piProvider: string;
  profileId: string;
  credential?: Credential | null;
  apiBase: string;
  token: string;
}

export interface CompactRequest {
  type: "compact";
  turnId: string;
  systemPrompt: string;
  provider?: RunTurnRequest["provider"];
  model?: string;
  sessionState?: unknown;
  apiBase: string;
  token: string;
}

/**
 * 跑一次订阅计划的登录(设备码 / 浏览器授权)。
 *
 * 和 run_turn 分开是必然的:授权是**用户在界面上**完成的,可能几十秒到几分钟,而且要往返
 * 提问-作答;塞进一轮对话里既拿不到 UI,也会把这一轮卡死。
 */
export interface AuthLoginRequest {
  type: "auth_login";
  loginId: string;
  /** pi 内置 Provider 的 id(授权流程在它里面)。 */
  piProvider: string;
  /** 凭据落库时定位档案。 */
  profileId: string;
  apiBase: string;
  token: string;
  /** 重新登录时把已有凭据带上。 */
  credential?: Credential | null;
}

/** 用户对某个 auth_prompt 的作答。 */
export interface AuthAnswerRequest {
  type: "auth_answer";
  promptId: string;
  answer: string;
}

/** 放弃这次登录(用户关掉了弹窗)。 */
export interface AuthCancelRequest {
  type: "auth_cancel";
  loginId: string;
}

export type Request =
  | RunTurnRequest
  | GatewayCompletionRequest
  | SteerRequest
  | QueueRequest
  | AbortRequest
  | CompactRequest
  | RefreshCredentialRequest
  | AuthLoginRequest
  | AuthAnswerRequest
  | AuthCancelRequest;


/** Sidecar -> backend events. */
export type Event =
  | { type: "ready" }
  | { type: "text_delta"; turnId: string; delta: string }
  | { type: "thinking_delta"; turnId: string; delta: string }
  | { type: "thinking_end"; turnId: string }
  | { type: "tool_start"; turnId: string; toolCallId: string; name: string; args: unknown }
  | { type: "tool_end"; turnId: string; toolCallId: string; result: unknown; isError: boolean }
  | {
      /** 子智能体内部的一步工具调用,挂在发起它的 run_subagent 调用(parentCallId)名下。 */
      type: "subtool";
      turnId: string;
      parentCallId: string;
      phase: "start" | "end";
      toolCallId: string;
      toolName: string;
      args?: unknown;
      result?: unknown;
      isError?: boolean;
    }
  | {
      /** 后台派发的子智能体跑完了:把存档填回发起它的 run_subagent 卡(parentCallId)。 */
      type: "subagent_result";
      turnId: string;
      parentCallId: string;
      archive: { task: string; steps: number; error: string | null; trace: unknown[] };
    }
  | {
      type: "turn_done";
      turnId: string;
      text: string;
      sessionState: unknown;
      usage?: Record<string, unknown>;
      /** 本轮结束时的上下文水位。窗口按当前模型给 —— 换模型上限就变。 */
      context?: { tokens: number; window: number };
      /** 本轮开始前发生的压缩;没发生则不带。前端据此在对话流里插一条标记 ——
       *  压缩必须被看见,否则用户不知道早期消息已经不在上下文里了。 */
      compaction?: { droppedMessages: number; tokensBefore: number; tokensAfter: number; summary: string } | null;
    }
  | { type: "queued"; turnId: string; mode: "steer" | "follow_up"; pending: boolean }
  | { type: "aborted"; turnId: string }
  | { type: "credential_refreshed"; turnId: string; refreshed: boolean }
  | { type: "gateway_done"; turnId: string; text: string; usage?: Record<string, unknown> }
  | {
      type: "compacted";
      turnId: string;
      sessionState: unknown;
      context?: { tokens: number; window: number };
      compaction?: { droppedMessages: number; tokensBefore: number; tokensAfter: number; summary: string } | null;
    }
  | { type: "error"; turnId: string | null; message: string }
  // ── 登录流程 ───────────────────────────────────────────────────────────────
  // pi 要展示给用户的东西(授权链接、设备码、进度)原样转发:`event` 就是 pi 的 AuthEvent,
  // 不在这里翻译成自定义结构 —— 上游加一种事件类型时,前端至少还能拿到原文。
  | { type: "auth_event"; loginId: string; event: Record<string, unknown> }
  | {
      type: "auth_prompt";
      loginId: string;
      promptId: string;
      promptType: "text" | "secret" | "select" | "manual_code";
      message: string;
      placeholder?: string;
      options?: readonly { id: string; label: string; description?: string }[];
    }
  /** 登录成功。models = 该账号实际可用的模型目录(Copilot 随档位变、OpenRouter 有几百个)。 */
  | {
      type: "auth_done";
      loginId: string;
      models: {
        id: string;
        name: string;
        contextWindow?: number;
        maxTokens?: number;
        /** 美元 / 百万 token。仅用于预填计价规则,不参与实际计费。 */
        cost?: { input: number; output: number; cacheRead: number; cacheWrite: number };
      }[];
    };

export function send(event: Event): void {
  process.stdout.write(JSON.stringify(event) + "\n");
}

export function log(...args: unknown[]): void {
  process.stderr.write("[sidecar] " + args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" ") + "\n");
}
