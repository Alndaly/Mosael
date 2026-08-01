/**
 * 思考档位到底发出去了什么 —— 断言**真实请求体**。
 *
 * 这一类 bug 连着骗过了两轮修改:第一次 model.reasoning 默认 false,pi 里每条关思考的分支
 * 都不触发,请求里什么都没有;第二次改成 true 之后又变成永远发 disabled,因为 pi 的 Agent
 * 把档位放在 options.reasoning,而拼请求体的地方读 options.reasoningEffort,两者之间的翻译
 * 只发生在 streamSimple 里,而我们调的是 stream。
 *
 * 两次的共同点:类型全绿、单测全绿、界面看起来也在跑。只有把网络那一层拦下来看真实 body
 * 才抓得到。所以这条测试拦 fetch。
 */
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const outdir = path.join(import.meta.dirname, "..", "dist");
mkdirSync(outdir, { recursive: true });
const outfile = path.join(outdir, "pi.wire.mjs");
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

/** 跑一轮,把发往供应商的第一个请求体截下来。响应故意给个错,我们只要 body。 */
async function captureRequest(thinkingLevel) {
  const original = globalThis.fetch;
  let captured = null;
  globalThis.fetch = async (url, init) => {
    if (captured === null && init?.body) captured = JSON.parse(String(init.body));
    return new Response("nope", { status: 500, statusText: "stubbed" });
  };
  try {
    await runPiTurn(
      {
        systemPrompt: "s",
        prompt: "1+1",
        provider: { baseUrl: "https://api.deepseek.com", apiKey: "k", vendor: "deepseek" },
        model: "deepseek-v4-flash",
        tools: [],
        apiBase: "http://127.0.0.1:1",
        token: "t",
        thinkingLevel,
      },
      {
        onDelta: () => {},
        onThinking: () => {},
        onThinkingEnd: () => {},
        onToolStart: () => {},
        onToolEnd: () => {},
      },
    );
  } catch {
    // 供应商返回 500 —— 无所谓,请求体已经拿到了
  } finally {
    globalThis.fetch = original;
  }
  return captured;
}

test("思考=高 → 请求里带 thinking enabled", async () => {
  const body = await captureRequest("high");
  assert.ok(body, "应当抓到一个请求");
  assert.deepEqual(body.thinking, { type: "enabled" }, `实际 body.thinking=${JSON.stringify(body.thinking)}`);
});

test("思考=关 → 请求里带 thinking disabled", async () => {
  const body = await captureRequest("off");
  assert.ok(body, "应当抓到一个请求");
  assert.deepEqual(body.thinking, { type: "disabled" }, `实际 body.thinking=${JSON.stringify(body.thinking)}`);
});
