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

import type { Agent } from "@earendil-works/pi-agent-core";

import { log, send, type Request } from "./protocol.js";
import { runPiTurn } from "./pi.js";
import { buildAllTools } from "./tools.js";

/**
 * Turns currently running, so a later frame can reach into one.
 *
 * Steering is only meaningful while a turn is in flight, which means the Agent has to be
 * addressable from outside the call that is awaiting it.
 */
const active = new Map<string, Agent>();

async function handleRunTurn(msg: Extract<Request, { type: "run_turn" }>): Promise<void> {
  const { turnId, prompt } = msg;
  if (msg.provider?.baseUrl && msg.model) {
    const tools = await buildAllTools(msg.apiBase, msg.token, msg.workspaceId);
    const result = await runPiTurn(
      {
        systemPrompt: msg.systemPrompt,
        prompt,
        provider: { baseUrl: msg.provider.baseUrl, apiKey: msg.provider.apiKey },
        model: msg.model,
        tools,
        sessionState: msg.sessionState,
        onAgentReady: (agent) => active.set(turnId, agent),
      },
      {
        onDelta: (delta) => send({ type: "text_delta", turnId, delta }),
        onToolStart: (toolCallId, name, args) => send({ type: "tool_start", turnId, toolCallId, name, args }),
        onToolEnd: (toolCallId, result, isError) => send({ type: "tool_end", turnId, toolCallId, result, isError }),
      },
    );
    if (result.aborted) send({ type: "aborted", turnId });
    // 模型调用失败但没产出任何文本 → 报错,别把它当成一轮"成功但空"的回答。
    else if (result.errorMessage && !result.text.trim()) {
      send({ type: "error", turnId, message: result.errorMessage });
      return;
    }
    send({ type: "turn_done", turnId, text: result.text, sessionState: result.sessionState });
    return;
  }
  // 无 provider:退回 echo(便于纯传输测试)
  const text = `「sidecar echo」未提供 provider/model。收到 prompt:${prompt ?? ""}`;
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
      if (msg.type === "run_turn") {
        // Deliberately NOT awaited. Awaiting here stops stdin from being read until the turn
        // ends, which would make steer and abort frames — the only frames that matter while a
        // turn is running — impossible to deliver.
        void handleRunTurn(msg)
          .catch((err) => send({ type: "error", turnId: msg.turnId, message: String(err) }))
          .finally(() => active.delete(msg.turnId));
      } else if (msg.type === "steer") {
        const agent = active.get(msg.turnId);
        if (!agent) {
          // The turn finished between the user typing and this frame arriving. Saying so lets
          // the backend send it as an ordinary next turn instead of dropping it.
          send({ type: "queued", turnId: msg.turnId, mode: msg.mode ?? "steer", pending: false });
        } else {
          const message = { role: "user" as const, content: msg.prompt, timestamp: Date.now() };
          if (msg.mode === "follow_up") agent.followUp(message);
          else agent.steer(message);
          send({ type: "queued", turnId: msg.turnId, mode: msg.mode ?? "steer", pending: true });
        }
      } else if (msg.type === "queue") {
        const agent = active.get(msg.turnId);
        if (agent) {
          agent.clearSteeringQueue();
          for (const prompt of msg.prompts) {
            agent.steer({ role: "user" as const, content: prompt, timestamp: Date.now() });
          }
        }
        send({ type: "queued", turnId: msg.turnId, mode: "steer", pending: Boolean(agent) && msg.prompts.length > 0 });
      } else if (msg.type === "abort") {
        active.get(msg.turnId)?.abort();
      } else {
        log("unknown message type:", (msg as { type?: string }).type ?? "(none)");
      }
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
