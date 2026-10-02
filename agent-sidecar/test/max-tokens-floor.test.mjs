/**
 * 发出去的请求**至少留得出一段回答**:不发一个几乎没有输出额度的请求。
 *
 * pi 在每次请求前按「窗口 − 已用 − 4096」夹 max_tokens(pi-ai api/simple-options.clampMaxTokensToContext),
 * 下限是 1。上下文一满,模型就只剩几个 token:用户看到「我」「抱歉」这类碎片,或者一句话说到冒号就没了。
 *
 * 两件事:
 *   · 轮内裁工具结果时,裁的若是锚点(上一条助手消息的用量)之前的内容,锚点的数要跟着减 —— 不减的话估算
 *     纹丝不动,裁了也白裁,max_tokens 照样被夹到底;
 *   · 裁到头还是留不出一段回答(固定开销本身就快占满窗口),就**不发**这个请求,报一句说得清的错
 *     (窗口太小、该在模型设置里填真实窗口),而不是让模型挤出半句话。
 *
 * 驱动真的 runPiTurn,拦 fetch 看真实请求体里的 max_tokens。
 */
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const outdir = path.join(import.meta.dirname, "..", "dist");
mkdirSync(outdir, { recursive: true });
const outfile = path.join(outdir, "pi.max-tokens.mjs");
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

const WINDOW = 24_000;

function okStream() {
  const chunk = (delta, finish = null, usage) =>
    `data: ${JSON.stringify({ id: "c", object: "chat.completion.chunk", created: 0, model: "m", choices: [{ index: 0, delta, finish_reason: finish }], ...(usage ? { usage } : {}) })}\n\n`;
  const body = chunk({ role: "assistant" }) + chunk({ content: "好的。" }) +
    chunk({}, "stop", { prompt_tokens: 100, completion_tokens: 5, total_tokens: 105 }) + "data: [DONE]\n\n";
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

const usage = (input, output = 100) => ({
  input, output, cacheRead: 0, cacheWrite: 0, totalTokens: input + output,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
});
const text = (value) => [{ type: "text", text: value }];

/** 上一轮:看了一次素材(一大段结果),然后说完了。上一条助手消息的用量 = 供应商上次读到的量。 */
function priorTurn({ resultChars, anchorInput }) {
  const now = Date.now() - 60_000;
  return [
    { role: "user", content: "看看素材", timestamp: now },
    {
      role: "assistant", api: "openai-completions", provider: "mosael", model: "m", stopReason: "toolUse", timestamp: now + 1,
      content: [{ type: "toolCall", id: "t0", name: "list_assets", arguments: {} }], usage: usage(2_000, 20),
    },
    {
      role: "toolResult", toolCallId: "t0", toolName: "list_assets", isError: false, timestamp: now + 2,
      content: text("很长的工具结果。".repeat(Math.ceil(resultChars / 8))),
    },
    {
      role: "assistant", api: "openai-completions", provider: "mosael", model: "m", stopReason: "stop", timestamp: now + 3,
      content: text("列完了。"), usage: usage(anchorInput),
    },
  ];
}

async function turn(sessionState) {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (_url, init) => {
    requests.push(JSON.parse(String(init.body)));
    return okStream();
  };
  try {
    const result = await runPiTurn(
      {
        systemPrompt: "s",
        prompt: "再来",
        provider: { baseUrl: "https://api.example.com/v1", apiKey: "k", vendor: "openai-compatible", contextWindow: WINDOW, maxOutputTokens: 4_096 },
        model: "m",
        tools: [],
        apiBase: "http://127.0.0.1:1",
        token: "t",
        thinkingLevel: "off",
        sessionState,
      },
      { onDelta: () => {}, onThinking: () => {}, onThinkingEnd: () => {}, onToolStart: () => {}, onToolEnd: () => {} },
    );
    return { result, requests };
  } finally {
    globalThis.fetch = original;
  }
}

const maxTokensOf = (body) => body.max_completion_tokens ?? body.max_tokens;

test("裁掉上一轮那段大结果就留得出回答:请求的 max_tokens 不再被夹到几百", async () => {
  //: 19,000 + 100 ≈ 窗口的 79%:不到轮前压缩的 80%,而 24,000 − 19,1xx − 4,096 只剩八百来个 token。
  const { result, requests } = await turn(priorTurn({ resultChars: 56_000, anchorInput: 19_000 }));
  assert.equal(result.errorMessage, undefined, result.errorMessage);
  assert.equal(requests.length, 1);
  assert.ok(maxTokensOf(requests[0]) >= 1_024, `max_tokens 被夹到 ${maxTokensOf(requests[0])}`);
});

test("没有可裁的、固定开销自己就快占满窗口:不发请求,报一句说得清的错", async () => {
  const { result, requests } = await turn(priorTurn({ resultChars: 200, anchorInput: 19_000 }));
  assert.equal(requests.length, 0, `还是发了一个 max_tokens=${requests[0] && maxTokensOf(requests[0])} 的请求`);
  assert.match(result.errorMessage ?? "", /上下文窗口/);
  assert.equal(result.errorCode, "context_full", "要让后端说成「窗口太小」,而不是「检查供应商配置」");
});
