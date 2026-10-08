/**
 * 「停止」之后:这一轮记成停止(不是失败),停之前说出来的那段留在记忆里。
 *
 * 两个现场(隔离环境 + 脚本化的假模型):
 *   1. 停在工具执行中(最常见:正等着批一张卡)—— pi 把被中止的那次模型请求记成 stopReason="error"
 *      (「This operation was aborted」),`agent.signal` 运行结束后就没了,于是这一轮被报成「智能体执行失败」。
 *   2. 流式出字时停 —— 部分回答落库、用户看着它,可 pi 发下一次请求时整条丢掉 aborted 的助手消息:用户说「接着说」,
 *      模型一个字都不记得,下一次请求里是连着两条用户消息。
 *
 * 跑法:node agent-sidecar/test/stop-keeps-what-was-said.test.mjs
 */
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import http from "node:http";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const outdir = path.join(import.meta.dirname, "..", "dist");
mkdirSync(outdir, { recursive: true });
async function load(entry, name) {
  const outfile = path.join(outdir, name);
  await build({
    entryPoints: [path.join(import.meta.dirname, "..", "src", entry)],
    outfile,
    format: "esm",
    bundle: true,
    platform: "node",
    packages: "external",
    ignoreAnnotations: true,
  });
  return import(pathToFileURL(outfile).href);
}
const { keepWhatWasSaid, STOPPED_NOTE, STOPPED_EMPTY } = await load("stopped.ts", "stopped.test-bundle.mjs");
const { runPiTurn } = await load("pi.ts", "pi.stop-keeps.mjs");

const text = (t) => [{ type: "text", text: t }];

test("被停掉的助手消息改成普通的一条:留下说过的字、注明没说完;没出字的换成一句「被停止」", () => {
  const before = [
    { role: "user", content: text("旧问题") },
    { role: "assistant", stopReason: "aborted", content: text("上一轮被停的不归这一轮管") },
  ];
  const turn = [
    { role: "user", content: text("写一篇长文") },
    {
      role: "assistant",
      stopReason: "aborted",
      errorMessage: "Request was aborted",
      usage: { input: 10, output: 3 },
      content: [{ type: "thinking", thinking: "想" }, ...text("第一段"), { type: "toolCall", id: "c1", name: "x", arguments: {} }],
    },
    { role: "user", content: text("插话") },
    { role: "assistant", stopReason: "error", errorMessage: "This operation was aborted", content: [] },
  ];
  const out = keepWhatWasSaid([...before, ...turn], before.length);
  assert.deepEqual(out.slice(0, 2), before, "这一轮之前的不动");
  const cut = out[3];
  assert.equal(cut.stopReason, "stop");
  assert.equal(cut.errorMessage, undefined);
  assert.deepEqual(cut.content, text(`第一段\n\n${STOPPED_NOTE}`), "只留文字:残缺的工具调用、思考块重放出去供应商会拒");
  assert.deepEqual(cut.usage, { input: 10, output: 3 }, "供应商回报的用量留着(水位按它算)");
  assert.deepEqual(out[5].content, text(STOPPED_EMPTY));
  const untouched = [{ role: "user", content: text("x") }, { role: "assistant", stopReason: "stop", content: text("y") }];
  assert.equal(keepWhatWasSaid(untouched, 0), untouched, "没有要改的就是同一个数组");
});

/** OpenAI 兼容上游:第一次请求回一个工具调用,之后的请求慢慢吐字(会被中止)。 */
function upstream({ toolFirst }) {
  const state = { requests: 0 };
  const server = http.createServer((req, res) => {
    state.requests += 1;
    req.resume();
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
    const chunk = (delta, finish = null) =>
      res.write(`data: ${JSON.stringify({ id: "c", object: "chat.completion.chunk", created: 0, model: "m", choices: [{ index: 0, delta, finish_reason: finish }] })}\n\n`);
    if (toolFirst && state.requests === 1) {
      chunk({ role: "assistant", tool_calls: [{ index: 0, id: "call-1", type: "function", function: { name: "wait_for_card", arguments: "{}" } }] });
      chunk({}, "tool_calls");
      res.end("data: [DONE]\n\n");
      return;
    }
    let n = 0;
    const timer = setInterval(() => {
      n += 1;
      if (n > 200) {
        clearInterval(timer);
        res.end("data: [DONE]\n\n");
        return;
      }
      chunk(n === 1 ? { role: "assistant", content: "字" } : { content: "字" });
    }, 40);
    res.on("close", () => clearInterval(timer));
  });
  return { server, state };
}

const handlers = (extra = {}) => ({
  onDelta: () => {},
  onThinking: () => {},
  onThinkingEnd: () => {},
  onToolStart: () => {},
  onToolEnd: () => {},
  ...extra,
});

async function listen(server) {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return server.address().port;
}

test("停在工具执行中(等着批卡)按停止:记成停止,不是「智能体执行失败」", async () => {
  const { server } = upstream({ toolFirst: true });
  const port = await listen(server);
  let agent = null;
  let stoppedByUser = false;
  //: 一个阻塞着等人的工具(和确认卡同一个样子):停止时它的等待被中止。
  const waitForCard = {
    name: "wait_for_card",
    label: "wait_for_card",
    description: "等用户批卡",
    parameters: { type: "object", properties: {} },
    execute: (_id, _params, signal) =>
      new Promise((_resolve, reject) => {
        setTimeout(() => {
          stoppedByUser = true; // index.ts 收到 abort 帧时记下的那件事
          agent.abort();
        }, 100);
        signal?.addEventListener("abort", () => reject(new Error("GET /api/confirmations/c1 已取消(这一轮被停止)")), { once: true });
      }),
  };
  try {
    const result = await runPiTurn(
      {
        systemPrompt: "s",
        prompt: "建一个工作流",
        provider: { baseUrl: `http://127.0.0.1:${port}/v1`, apiKey: "k", vendor: "openai" },
        model: "m",
        tools: [waitForCard],
        apiBase: "http://127.0.0.1:1",
        token: "t",
        thinkingLevel: "off",
        wasStopped: () => stoppedByUser,
        onAgentReady: (ready) => {
          agent = ready;
        },
      },
      handlers(),
    );
    assert.equal(result.aborted, true, "按了停止的这一轮应当报「被停止」");
    assert.equal(result.errorMessage, undefined, "停止不是失败(此前是「This operation was aborted」)");
    const last = result.sessionState.at(-1);
    assert.equal(last.role, "assistant");
    assert.notEqual(last.stopReason, "error", "存进记忆的最后一条不该是一条会被整条丢掉的 error 消息");
    assert.deepEqual(last.content, text(STOPPED_EMPTY));
    assert.ok(
      result.sessionState.some((m) => m.role === "toolResult"),
      "已经发生的工具调用和它的结果留在记忆里",
    );
  } finally {
    server.closeAllConnections();
    server.close();
  }
});

test("流式出字时按停止:屏上那段部分回答留在记忆里,标明没说完", async () => {
  const { server } = upstream({ toolFirst: false });
  const port = await listen(server);
  let agent = null;
  let seen = 0;
  try {
    const result = await runPiTurn(
      {
        systemPrompt: "s",
        prompt: "写一篇很长的文章",
        provider: { baseUrl: `http://127.0.0.1:${port}/v1`, apiKey: "k", vendor: "openai" },
        model: "m",
        tools: [],
        apiBase: "http://127.0.0.1:1",
        token: "t",
        thinkingLevel: "off",
        wasStopped: () => seen >= 3,
        onAgentReady: (ready) => {
          agent = ready;
        },
      },
      handlers({
        onDelta: () => {
          seen += 1;
          if (seen === 3) agent.abort();
        },
      }),
    );
    assert.equal(result.aborted, true);
    const last = result.sessionState.at(-1);
    assert.equal(last.stopReason, "stop", "aborted 的助手消息 pi 下一轮会整条丢掉 —— 那就等于模型没说过这段");
    const said = last.content.map((block) => block.text).join("");
    assert.ok(said.startsWith(result.text), `记忆里要有屏上那段:${said}`);
    assert.ok(said.endsWith(STOPPED_NOTE));
  } finally {
    server.closeAllConnections();
    server.close();
  }
});
