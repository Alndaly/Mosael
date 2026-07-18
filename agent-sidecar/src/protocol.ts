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

export type Request = RunTurnRequest;

/** Sidecar -> backend events. */
export type Event =
  | { type: "ready" }
  | { type: "text_delta"; turnId: string; delta: string }
  | { type: "tool_start"; turnId: string; toolCallId: string; name: string; args: unknown }
  | { type: "tool_end"; turnId: string; toolCallId: string; result: unknown }
  | { type: "turn_done"; turnId: string; text: string; sessionState: unknown }
  | { type: "error"; turnId: string | null; message: string };

export function send(event: Event): void {
  process.stdout.write(JSON.stringify(event) + "\n");
}

export function log(...args: unknown[]): void {
  process.stderr.write("[sidecar] " + args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" ") + "\n");
}
