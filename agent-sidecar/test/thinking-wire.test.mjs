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

/**
 * 上面两条走的是 **api.deepseek.com** —— 那会命中 pi 里按 baseUrl 认出 deepseek 的分支,
 * 发的是 `thinking: {type}`。而**第三方中转**(通用 OpenAI 兼容端点)认不出供应商,走的是
 * 最后那两条 `reasoning_effort` 分支 —— 那条路此前一条测试都没有,于是漏了整整一个 bug:
 *
 * 后端查证过 deepseek-v4 收 reasoning_effort 的哪几个值、把 thinkingLevelMap 给了下来、
 * 界面上也据此列出了档位,而 compat.supportsReasoningEffort 默认 false 在最后一步把它丢了。
 * 结果和 1.3.1 修的那个 bug 一模一样:**四个档位发出去的请求逐字节相同**。
 */
async function captureVia(provider, thinkingLevel, model = "deepseek-v4") {
  const original = globalThis.fetch;
  let captured = null;
  globalThis.fetch = async (url, init) => {
    if (captured === null && init?.body) captured = JSON.parse(String(init.body));
    return new Response("nope", { status: 500, statusText: "stubbed" });
  };
  try {
    await runPiTurn(
      { systemPrompt: "s", prompt: "1+1", provider, model, tools: [], apiBase: "http://127.0.0.1:1", token: "t", thinkingLevel },
      { onDelta: () => {}, onThinking: () => {}, onThinkingEnd: () => {}, onToolStart: () => {}, onToolEnd: () => {} },
    );
  } catch {
    /* 500 是故意的,body 已经拿到 */
  } finally {
    globalThis.fetch = original;
  }
  return captured;
}

/** 第三方中转:认不出供应商,只能靠后端给的 thinkingLevelMap。 */
const relay = {
  baseUrl: "https://relay.example.com/v1",
  apiKey: "k",
  vendor: "openai-compatible",
  thinkingLevelMap: { off: null, low: "low", medium: null, high: "high" },
};

test("中转端点:给了 thinkingLevelMap 就该发 reasoning_effort,不能再被 supportsReasoningEffort 默认关掉", async () => {
  const low = await captureVia(relay, "low");
  const high = await captureVia(relay, "high");
  assert.equal(low?.reasoning_effort, "low", `低档实际 body=${JSON.stringify(low)}`);
  assert.equal(high?.reasoning_effort, "high", `高档实际 body=${JSON.stringify(high)}`);
});

test("中转端点:四个档位发出去的东西必须彼此不同 —— 这正是上一版的 bug", async () => {
  const seen = new Map();
  for (const level of ["off", "low", "medium", "high"]) {
    const body = await captureVia(relay, level);
    seen.set(level, body?.reasoning_effort ?? null);
  }
  // off 和 medium 这个模型不支持(map 里是 null),该发不出去;low/high 必须各是各的。
  assert.equal(seen.get("low"), "low");
  assert.equal(seen.get("high"), "high");
  assert.notEqual(seen.get("low"), seen.get("high"), "低和高不能发出同一个值");
});

test("没给 thinkingLevelMap 的端点仍然保守 —— 不认识的模型不硬塞 reasoning_effort", async () => {
  const unknown = { baseUrl: "https://relay.example.com/v1", apiKey: "k", vendor: "openai-compatible" };
  const body = await captureVia(unknown, "high", "some-local-model");
  assert.equal(body?.reasoning_effort, undefined, `不该带 reasoning_effort,实际 body=${JSON.stringify(body)}`);
});
