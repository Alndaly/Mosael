/**
 * Open Studio agent sidecar — entry point (S1 scaffold).
 *
 * A long-lived Node process the Python backend spawns once and drives over
 * stdio (see protocol.ts). It will embed pi's `Agent` (pi-agent-core) to run
 * turns, bridge Open Studio's tools, and stream events back. S1 only proves the
 * transport: it echoes each run_turn's prompt back as streamed text. pi is
 * wired in S2.
 */
import * as readline from "node:readline";

import type { Agent } from "@earendil-works/pi-agent-core";

import { answerAuthPrompt, runAuthLogin } from "./auth.js";
import { log, send, type Request } from "./protocol.js";
import { installProxyFromEnv } from "./proxy.js";
import { runPiTurn } from "./pi.js";
import { buildAllTools } from "./tools.js";

/**
 * Turns currently running, so a later frame can reach into one.
 *
 * Steering is only meaningful while a turn is in flight, which means the Agent has to be
 * addressable from outside the call that is awaiting it.
 */
const active = new Map<string, Agent>();

/** 进行中的登录:loginId -> 取消开关。授权可能持续几分钟,用户随时可能关掉弹窗。 */
const logins = new Map<string, AbortController>();

async function handleRunTurn(msg: Extract<Request, { type: "run_turn" }>): Promise<void> {
  const { turnId, prompt } = msg;
  // 订阅计划(piProvider)没有用户填的 baseUrl —— 端点在 pi 的 Provider 定义里。
  if ((msg.provider?.baseUrl || msg.provider?.piProvider) && msg.model) {
    const tools = await buildAllTools(msg.apiBase, msg.token, msg.workspaceId, msg.sessionId);
    const result = await runPiTurn(
      {
        systemPrompt: msg.systemPrompt,
        prompt,
        provider: msg.provider,
        model: msg.model,
        tools,
        apiBase: msg.apiBase,
        token: msg.token,
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
    send({ type: "turn_done", turnId, text: result.text, sessionState: result.sessionState, usage: result.usage });
    return;
  }
  // 无 provider:退回 echo(便于纯传输测试)
  const text = `「sidecar echo」未提供 provider/model。收到 prompt:${prompt ?? ""}`;
  for (const ch of text) send({ type: "text_delta", turnId, delta: ch });
  send({ type: "turn_done", turnId, text, sessionState: null, usage: { requests: 1 } });
}

async function main(): Promise<void> {
  // 必须在任何请求之前:setGlobalDispatcher 只影响之后发起的请求。
  installProxyFromEnv();
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
      } else if (msg.type === "auth_login") {
        const controller = new AbortController();
        logins.set(msg.loginId, controller);
        // 同样不 await:授权要等用户操作,await 会让 stdin 停读,作答帧永远送不进来。
        void runAuthLogin(msg, controller.signal)
          .catch((err) => {
            // 授权失败的原因往往在栈里(某一步 pi 内部拿不到东西),而协议帧只带 message。
            // stderr 是调试通道,不进协议,所以这里可以放全量。
            log("auth login failed:", (err as Error)?.stack ?? String(err));
            send({ type: "error", turnId: msg.loginId, message: String(err) });
          })
          .finally(() => logins.delete(msg.loginId));
      } else if (msg.type === "auth_answer") {
        if (!answerAuthPrompt(msg.promptId, msg.answer)) {
          log("no pending auth prompt for", msg.promptId);
        }
      } else if (msg.type === "auth_cancel") {
        logins.get(msg.loginId)?.abort();
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
