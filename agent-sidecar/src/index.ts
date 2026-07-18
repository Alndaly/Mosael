/**
 * Mibu agent sidecar — entry point (S1 scaffold).
 *
 * A long-lived Node process the Python backend spawns once and drives over
 * stdio (see protocol.ts). It will embed pi's `Agent` (pi-agent-core) to run
 * turns, bridge Mibu's tools, and stream events back. S1 only proves the
 * transport: it echoes each run_turn's prompt back as streamed text. pi is
 * wired in S2.
 */
import * as readline from "node:readline";

import { log, send, type Request } from "./protocol.js";

async function handleRunTurn(msg: Extract<Request, { type: "run_turn" }>): Promise<void> {
  const { turnId, prompt } = msg;
  const text = `「sidecar echo」pi 尚未接入(S1)。收到 prompt:${prompt ?? ""}`;
  for (const ch of text) send({ type: "text_delta", turnId, delta: ch });
  send({ type: "turn_done", turnId, text, sessionState: null });
}

async function main(): Promise<void> {
  const rl = readline.createInterface({ input: process.stdin });
  send({ type: "ready" });
  log("started; awaiting run_turn frames on stdin");
  for await (const line of rl) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let msg: Request;
    try {
      msg = JSON.parse(trimmed) as Request;
    } catch {
      log("ignoring non-JSON line:", trimmed.slice(0, 120));
      continue;
    }
    try {
      if (msg.type === "run_turn") await handleRunTurn(msg);
      else log("unknown message type:", (msg as { type?: string }).type ?? "(none)");
    } catch (err) {
      send({ type: "error", turnId: (msg as { turnId?: string }).turnId ?? null, message: String(err) });
    }
  }
  log("stdin closed; exiting");
}

main().catch((err) => {
  log("fatal:", err);
  process.exit(1);
});
