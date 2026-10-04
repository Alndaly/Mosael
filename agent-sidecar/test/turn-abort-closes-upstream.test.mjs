/**
 * 按「停止」之后,这一轮对供应商的那条流式连接**真的断开**,之后一个字也不再流进来。
 *
 * 后端那边的取消(工作流 / 任务)此前只改一行状态,在途的请求照样答完(Ollama 一直生成到后端重启、付费 API 照样计费)。
 * 对话轮次走 sidecar:停止帧 → agent.abort()。这里核对那一下确实传到了 fetch —— 上游是本机一个真的、慢的流式服务,
 * 每 50 毫秒吐一块,看它那一侧什么时候看到连接关闭,以及停止之后还有没有字进到这一轮。
 *
 * 跑法:node agent-sidecar/test/turn-abort-closes-upstream.test.mjs
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
const outfile = path.join(outdir, "pi.turn-abort.mjs");
await build({
  entryPoints: [path.join(import.meta.dirname, "..", "src", "pi.ts")],
  outfile,
  format: "esm",
  bundle: true,
  platform: "node",
  packages: "external",
  ignoreAnnotations: true,
});
const { runPiTurn } = await import(pathToFileURL(outfile).href);

/** 一个慢的 OpenAI 兼容流式上游:收到请求就每 50ms 吐一块,对方断开就停。 */
function slowUpstream() {
  const state = { requests: 0, chunksSent: 0, closedAt: null, finished: false };
  const server = http.createServer((req, res) => {
    state.requests += 1;
    req.resume();
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
    let n = 0;
    const timer = setInterval(() => {
      n += 1;
      if (n > 200) {
        clearInterval(timer);
        res.end("data: [DONE]\n\n");
        state.finished = true;
        return;
      }
      const chunk = {
        id: "c1",
        object: "chat.completion.chunk",
        created: 0,
        model: "m",
        choices: [{ index: 0, delta: n === 1 ? { role: "assistant", content: "字" } : { content: "字" }, finish_reason: null }],
      };
      res.write(`data: ${JSON.stringify(chunk)}\n\n`);
      state.chunksSent += 1;
    }, 50);
    res.on("close", () => {
      clearInterval(timer);
      if (!state.finished && state.closedAt === null) state.closedAt = performance.now();
    });
  });
  return { server, state };
}

test("停止之后供应商那条流式连接当场断开,之后一个字也不再进来", async () => {
  const { server, state } = slowUpstream();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  let agent = null;
  const deltas = [];
  let abortedAt = null;
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
        onAgentReady: (ready) => {
          agent = ready;
        },
      },
      {
        onDelta: (delta) => {
          deltas.push({ at: performance.now(), delta });
          if (deltas.length === 3) {
            abortedAt = performance.now();
            agent.abort();
          }
        },
        onThinking: () => {},
        onThinkingEnd: () => {},
        onToolStart: () => {},
        onToolEnd: () => {},
      },
    );
    // pi 的 Agent 被 abort 时 prompt() 不抛、只记一条 stopReason="aborted" 的消息:这一轮照样要报「被停止」,
    // 否则后端把「还没出字就停了」当成「模型什么都没回」。
    assert.equal(result.aborted, true, "这一轮应当报「被停止」");
    assert.equal(result.errorMessage, undefined);
    // 上游那一侧:连接断开发生在停止之后一秒内,而不是吐完 200 块(10 秒)。
    for (let i = 0; i < 100 && state.closedAt === null; i++) await new Promise((r) => setTimeout(r, 10));
    assert.ok(state.closedAt !== null, "上游应当看到连接关闭");
    assert.ok(state.closedAt - abortedAt < 1000, `停止后 ${state.closedAt - abortedAt}ms 才断开`);
    assert.equal(state.finished, false, "上游没有生成到底");
    assert.equal(state.requests, 1, "停止之后不再重发");
    // 停止之后一个字也不再进到这一轮。
    assert.deepEqual(deltas.filter((one) => one.at > abortedAt), []);
    const sentAtClose = state.chunksSent;
    await new Promise((r) => setTimeout(r, 300));
    assert.equal(state.chunksSent, sentAtClose, "断开之后上游也不再往外写");
  } finally {
    server.close();
  }
});

test("还没出字就按停止:连接照样断开,这一轮报「被停止」而不是「模型什么都没回」", async () => {
  //: 上游收到请求后憋着不回(思考中 / 本地模型冷启动)。
  const state = { requests: 0, closedAt: null };
  let onRequest = () => {};
  const server = http.createServer((req, res) => {
    state.requests += 1;
    req.resume();
    res.on("close", () => {
      if (state.closedAt === null) state.closedAt = performance.now();
    });
    onRequest();
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  let agent = null;
  let abortedAt = null;
  onRequest = () => {
    abortedAt = performance.now();
    agent.abort();
  };
  try {
    const result = await runPiTurn(
      {
        systemPrompt: "s",
        prompt: "想一想再说",
        provider: { baseUrl: `http://127.0.0.1:${port}/v1`, apiKey: "k", vendor: "openai" },
        model: "m",
        tools: [],
        apiBase: "http://127.0.0.1:1",
        token: "t",
        thinkingLevel: "off",
        onAgentReady: (ready) => {
          agent = ready;
        },
      },
      { onDelta: () => {}, onThinking: () => {}, onThinkingEnd: () => {}, onToolStart: () => {}, onToolEnd: () => {} },
    );
    assert.equal(result.aborted, true);
    assert.equal(result.errorMessage, undefined, "停止不是失败");
    assert.equal(result.text, "");
    for (let i = 0; i < 100 && state.closedAt === null; i++) await new Promise((r) => setTimeout(r, 10));
    assert.ok(state.closedAt !== null && state.closedAt - abortedAt < 1000, "上游应当当场看到连接关闭");
    assert.equal(state.requests, 1, "停止之后不再重发");
  } finally {
    server.closeAllConnections();
    server.close();
  }
});
