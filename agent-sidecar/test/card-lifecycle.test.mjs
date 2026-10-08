/**
 * 等确认卡这件事和一轮的生命周期绑在一起(ADR 0007 修订 2026-10-08)——驱动**打包产物**,走真实的 stdin/stdout 协议。
 *
 *   1. 等卡时向后端报「等人中」(`awaiting_user` 成对):后端据此停掉整轮时限的表。此前 600 秒里包括等人的时间,
 *      先干两分钟活再开卡、人八分钟后回来,整轮已经被杀、卡还亮着。
 *   2. 等卡时按「停止」:这一轮报 `aborted`、照常 `turn_done`,**不发 `error`**(此前是「智能体执行失败」)。
 *   3. 卡等到点:先请后端作废这张卡(`POST /api/confirmations/<id>/expire`),再告诉模型「没做」—— 不然模型以为没做,
 *      用户回来一点批准,动作却发生了。
 *
 * 跑法:node agent-sidecar/test/card-lifecycle.test.mjs
 */
import { spawn } from "node:child_process";
import assert from "node:assert/strict";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const bundle = path.join(here, "..", "dist", "sidecar.cjs");

/** 假后端:一个开卡工具;卡一直 pending;记下作废请求。 */
function backend() {
  const state = { expired: [], toolCalls: 0 };
  const server = http.createServer((req, res) => {
    const json = (body) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(body));
    };
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      if (req.url === "/api/agent/tools") {
        return json([{ name: "create_workflow", description: "建工作流", parameters: { type: "object", properties: {} }, confirmation: true }]);
      }
      if (req.url === "/api/agent/tools/create_workflow") {
        state.toolCalls += 1;
        return json({ result: { confirmation_id: "c1", status: "pending" } });
      }
      if (req.url === "/api/confirmations/c1/expire" && req.method === "POST") {
        state.expired.push("c1");
        return json({ id: "c1", status: "expired", error: "wait_timeout" });
      }
      if (req.url === "/api/confirmations/c1") return json({ id: "c1", status: state.expired.length ? "expired" : "pending", result: null });
      res.writeHead(404);
      res.end("{}");
    });
  });
  return { server, state };
}

/** 假模型:第一次请求要调 create_workflow,之后回一句话。 */
function provider() {
  let requests = 0;
  const seen = [];
  const server = http.createServer((req, res) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      requests += 1;
      seen.push(JSON.parse(body || "{}"));
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      const chunk = (delta, finish = null) =>
        res.write(`data: ${JSON.stringify({ id: "c", object: "chat.completion.chunk", created: 0, model: "m", choices: [{ index: 0, delta, finish_reason: finish }] })}\n\n`);
      if (requests === 1) {
        chunk({ role: "assistant", tool_calls: [{ index: 0, id: "call-1", type: "function", function: { name: "create_workflow", arguments: "{}" } }] });
        chunk({}, "tool_calls");
      } else {
        chunk({ role: "assistant", content: "好的,没建。" });
        chunk({}, "stop");
      }
      res.end("data: [DONE]\n\n");
    });
  });
  return { server, seen };
}

async function listen(server) {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return `http://127.0.0.1:${server.address().port}`;
}

function sidecar(env = {}) {
  const child = spawn(process.execPath, [bundle], { stdio: ["pipe", "pipe", "pipe"], env: { ...process.env, ...env } });
  const events = [];
  let buffer = "";
  child.stdout.on("data", (chunk) => {
    buffer += chunk;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      try {
        events.push(JSON.parse(line));
      } catch {
        /* 日志行 */
      }
    }
  });
  const send = (frame) => child.stdin.write(JSON.stringify(frame) + "\n");
  const waitFor = (predicate, label, timeout = 10_000) =>
    new Promise((resolve, reject) => {
      const started = Date.now();
      const tick = setInterval(() => {
        const hit = events.find(predicate);
        if (hit) {
          clearInterval(tick);
          resolve(hit);
        } else if (Date.now() - started > timeout) {
          clearInterval(tick);
          reject(new Error(`等不到${label};收到的是 ${JSON.stringify(events.map((e) => e.type))}`));
        }
      }, 20);
    });
  return { child, events, send, waitFor };
}

function runTurn(send, turnId, apiBase, modelBase) {
  send({
    type: "run_turn",
    turnId,
    prompt: "建一个工作流",
    systemPrompt: "s",
    provider: { baseUrl: `${modelBase}/v1`, apiKey: "k", vendor: "openai" },
    model: "m",
    apiBase,
    token: "t",
    workspaceId: "w",
  });
}

// ① 等卡时按停止:报「等人中」→ 停止 → 「等完了」、aborted、turn_done,没有 error。
{
  const api = backend();
  const model = provider();
  const apiBase = await listen(api.server);
  const modelBase = await listen(model.server);
  const { child, events, send, waitFor } = sidecar();
  try {
    runTurn(send, "t1", apiBase, modelBase);
    await waitFor((e) => e.type === "awaiting_user" && e.waiting === true, "开始等人");
    send({ type: "abort", turnId: "t1" });
    const done = await waitFor((e) => e.type === "turn_done" || e.type === "error", "这一轮收尾");
    assert.equal(done.type, "turn_done", `停止被报成了失败:${JSON.stringify(done)}`);
    assert.ok(events.some((e) => e.type === "aborted" && e.turnId === "t1"), "没有报「被停止」");
    const waits = events.filter((e) => e.type === "awaiting_user").map((e) => e.waiting);
    assert.deepEqual(waits, [true, false], "等人中 / 等完了要成对,后端按计数停表");
    const last = done.sessionState.at(-1);
    assert.notEqual(last.stopReason, "error", "存进记忆的最后一条是会被 pi 整条丢掉的 error 消息");
  } finally {
    child.kill();
    api.server.close();
    model.server.close();
  }
}

// ② 卡等到点:先作废,再告诉模型「没做」。
{
  const api = backend();
  const model = provider();
  const apiBase = await listen(api.server);
  const modelBase = await listen(model.server);
  const { child, events, send, waitFor } = sidecar({ MOSAEL_CARD_WAIT_MS: "300" });
  try {
    runTurn(send, "t2", apiBase, modelBase);
    const end = await waitFor((e) => e.type === "tool_end" && e.toolCallId === "call-1", "工具调用结束");
    assert.deepEqual(api.state.expired, ["c1"], "卡等到点却没作废 —— 用户回来一点批准,动作照样发生");
    assert.equal(end.isError, true);
    assert.match(JSON.stringify(end.result), /已作废/, "模型要知道:卡作废了,动作没有执行");
    const done = await waitFor((e) => e.type === "turn_done" || e.type === "error", "这一轮收尾");
    assert.equal(done.type, "turn_done");
    assert.deepEqual(events.filter((e) => e.type === "awaiting_user").map((e) => e.waiting), [true, false]);
    // 模型下一次请求里看到的工具结果就是那句「已作废,没有执行」。
    const toolResult = model.seen.at(-1).messages.find((m) => m.role === "tool");
    assert.match(String(toolResult.content), /没有执行/);
  } finally {
    child.kill();
    api.server.close();
    model.server.close();
  }
}

console.log("PASS  等卡时报等人中;等卡时停止是停止不是失败;卡等到点先作废再说没做");
