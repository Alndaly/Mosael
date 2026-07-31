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
  systemPrompt: string;
  /** Prior turns, already trimmed by the backend (may be empty). */
  history?: Array<{ role: "user" | "assistant"; content: string }>;
  workspaceId: string;
  /** 发起本轮的智能体会话。工具调用带上它,确认卡才能只在这次对话里内联出现。 */
  sessionId?: string;
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
  | SteerRequest
  | QueueRequest
  | AbortRequest
  | AuthLoginRequest
  | AuthAnswerRequest
  | AuthCancelRequest;


/** Sidecar -> backend events. */
export type Event =
  | { type: "ready" }
  | { type: "text_delta"; turnId: string; delta: string }
  | { type: "tool_start"; turnId: string; toolCallId: string; name: string; args: unknown }
  | { type: "tool_end"; turnId: string; toolCallId: string; result: unknown; isError: boolean }
  | { type: "turn_done"; turnId: string; text: string; sessionState: unknown; usage?: Record<string, unknown> }
  | { type: "queued"; turnId: string; mode: "steer" | "follow_up"; pending: boolean }
  | { type: "aborted"; turnId: string }
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
      models: { id: string; name: string; contextWindow?: number; maxTokens?: number }[];
    };

export function send(event: Event): void {
  process.stdout.write(JSON.stringify(event) + "\n");
}

export function log(...args: unknown[]): void {
  process.stderr.write("[sidecar] " + args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" ") + "\n");
}
