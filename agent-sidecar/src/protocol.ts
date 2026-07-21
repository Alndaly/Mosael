/**
 * Wire protocol between the Python backend and this sidecar.
 *
 * Transport: newline-delimited JSON over stdio. The backend writes one
 * request object per line to our stdin; we write event objects to stdout,
 * one per line. stdout carries ONLY protocol JSON — all human/debug logging
 * goes to stderr (see log()).
 */

/** Backend -> sidecar. */
export interface RunTurnRequest {
  type: "run_turn";
  turnId: string;
  prompt: string;
  systemPrompt: string;
  /** Prior turns, already trimmed by the backend (may be empty). */
  history?: Array<{ role: "user" | "assistant"; content: string }>;
  workspaceId: string;
  /** Base URL + bearer token for calling Mibu's HTTP API from tools (S3+). */
  apiBase: string;
  token: string;
  /** Resolved provider for pi-ai (S2+): OpenAI-compatible endpoint + model. */
  provider?: { baseUrl: string; apiKey: string; vendor: string };
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

export type Request = RunTurnRequest | SteerRequest | QueueRequest | AbortRequest;

/** Sidecar -> backend events. */
export type Event =
  | { type: "ready" }
  | { type: "text_delta"; turnId: string; delta: string }
  | { type: "tool_start"; turnId: string; toolCallId: string; name: string; args: unknown }
  | { type: "tool_end"; turnId: string; toolCallId: string; result: unknown; isError: boolean }
  | { type: "turn_done"; turnId: string; text: string; sessionState: unknown; usage?: Record<string, unknown> }
  | { type: "queued"; turnId: string; mode: "steer" | "follow_up"; pending: boolean }
  | { type: "aborted"; turnId: string }
  | { type: "error"; turnId: string | null; message: string };

export function send(event: Event): void {
  process.stdout.write(JSON.stringify(event) + "\n");
}

export function log(...args: unknown[]): void {
  process.stderr.write("[sidecar] " + args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" ") + "\n");
}
