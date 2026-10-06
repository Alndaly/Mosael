/**
 * Gemini(API Key 连接,pi 的原生 Gemini Provider)真正发出去了什么 —— 对着一台本机假 Gemini 断言**真实请求体**。
 *
 * 最要紧的是思考签名:Gemini 3 每次函数调用都带回一个 `thoughtSignature`,下一次请求必须把它原样放回那个
 * functionCall part 上,否则整轮 400「Function call is missing a thought_signature」。这件事同时取决于三处:
 * 走的是原生协议而不是 OpenAI 兼容层(兼容层不带它)、我们造的模型和历史消息认得出是同一家同一个型号(否则 pi
 * 当成别家的历史把签名剥掉)、会话状态经后端存一遍(JSON 往返)之后签名还在。类型和单测都看不见,只有拦下网络才看得见。
 *
 * 回包是按官方文档的 REST 形状构造的录像(见 fixtures/gemini-thought-signatures.json),走真的 HTTP + SSE。
 */
import assert from "node:assert/strict";
import { mkdirSync, readFileSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";
import { Type } from "@earendil-works/pi-ai";

const outdir = path.join(import.meta.dirname, "..", "dist");
mkdirSync(outdir, { recursive: true });
const outfile = path.join(outdir, "pi.gemini-wire.mjs");
await build({
  entryPoints: [path.join(import.meta.dirname, "..", "src", "pi.ts")],
  outfile,
  format: "esm",
  bundle: true,
  platform: "node",
  packages: "external",
  ignoreAnnotations: true,
});
const { runPiTurn, runGatewayCompletion } = await import(pathToFileURL(outfile).href);

const fixture = JSON.parse(readFileSync(path.join(import.meta.dirname, "fixtures", "gemini-thought-signatures.json"), "utf-8"));
const SIG = fixture.signatures;
const KEY = "test-gemini-key";
// 机器上恰好有一把环境变量里的钥匙:钥匙空着时绝不能用它(那是别人的钱)。
process.env.GEMINI_API_KEY = "env-key-that-must-never-be-sent";

/** 一台假 Gemini:收下每个请求,按顺序回下一段 SSE。 */
async function fakeGemini(responses) {
  const queue = [...responses];
  const requests = [];
  const server = createServer((req, res) => {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", () => {
      requests.push({ method: req.method, url: req.url, headers: req.headers, body: raw ? JSON.parse(raw) : null });
      const chunks = queue.shift();
      if (!chunks) {
        res.writeHead(500, { "content-type": "application/json" });
        res.end(JSON.stringify({ error: { code: 500, message: "fixture exhausted", status: "INTERNAL" } }));
        return;
      }
      res.writeHead(200, { "content-type": "text/event-stream" });
      for (const chunk of chunks) res.write(`data: ${JSON.stringify(chunk)}\r\n\r\n`);
      res.end();
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  return { requests, baseUrl: `http://127.0.0.1:${port}/v1beta`, close: () => new Promise((r) => server.close(r)) };
}

/** 后端 sidecar_provider 给 Google 连接的那份(见 backend/app/domain/providers/runtime.py)。 */
function geminiProvider(baseUrl, extra = {}) {
  return {
    baseUrl,
    apiKey: KEY,
    vendor: "google",
    piProvider: "google",
    profileId: "profile-gemini",
    contextWindow: 1_000_000,
    maxOutputTokens: 32_768,
    // domain/providers/thinking 给 Gemini 3 的那张表:关不掉。
    thinkingLevelMap: { off: null, low: "low", medium: "medium", high: "high" },
    ...extra,
  };
}

const toolCalls = [];
const tools = [
  {
    name: "lookup_asset",
    label: "查素材",
    description: "Look up one asset by id.",
    parameters: Type.Object({ asset_id: Type.String() }),
    execute: async (toolCallId, params) => {
      toolCalls.push(["lookup_asset", toolCallId, params]);
      return { content: [{ type: "text", text: `asset ${params.asset_id}: 12s beach clip` }], details: {} };
    },
  },
  {
    name: "list_assets",
    label: "列素材",
    description: "List assets.",
    parameters: Type.Object({}),
    execute: async (toolCallId) => {
      toolCalls.push(["list_assets", toolCallId, {}]);
      return { content: [{ type: "text", text: "asset-42, asset-7" }], details: {} };
    },
  },
];

const handlers = () => ({
  onDelta: () => {},
  onThinking: () => {},
  onThinkingEnd: () => {},
  onToolStart: () => {},
  onToolEnd: () => {},
});

const modelParts = (body) => body.contents.filter((content) => content.role === "model").flatMap((content) => content.parts);
const callPart = (body, name, id) => modelParts(body).find((part) => part.functionCall?.name === name && part.functionCall?.id === id);

test("两轮、多步的工具调用:每个思考签名都原样回到它那个 functionCall 上", async () => {
  const gemini = await fakeGemini(fixture.responses);
  try {
    const first = await runPiTurn(
      {
        systemPrompt: "你是 Mosael 的智能体。",
        prompt: "这个素材是什么?",
        images: [{ type: "image", data: "aW1hZ2U=", mimeType: "image/png" }],
        provider: geminiProvider(gemini.baseUrl),
        model: fixture.model,
        tools,
        apiBase: "http://127.0.0.1:1",
        token: "t",
        thinkingLevel: "off",
      },
      handlers(),
    );
    assert.equal(first.errorMessage, undefined, `第一轮失败:${first.errorMessage}`);
    assert.equal(first.text, "It is a 12-second clip of a beach.");
    assert.equal(gemini.requests.length, 2, "第一轮应当是两次请求:调工具、再回答");

    const [step1, step2] = gemini.requests;
    // 走的是 Gemini 原生协议,不是 OpenAI 兼容层(那是 /openai/chat/completions、Bearer 鉴权)。
    assert.equal(step1.method, "POST");
    assert.match(step1.url, /^\/v1beta\/models\/gemini-3-flash-preview:streamGenerateContent\?alt=sse$/);
    assert.equal(step1.headers["x-goog-api-key"], KEY);
    assert.equal(step1.headers.authorization, undefined, "AI Studio 的钥匙不能当 Bearer 发");
    assert.ok(step1.body.tools[0].functionDeclarations.some((fn) => fn.name === "lookup_asset"));
    // 当前消息的图片直接作为视觉输入。
    const firstUser = step1.body.contents[0];
    assert.equal(firstUser.role, "user");
    assert.deepEqual(
      firstUser.parts.find((part) => part.inlineData),
      { inlineData: { mimeType: "image/png", data: "aW1hZ2U=" } },
    );
    // 「关」在关不掉思考的 Gemini 3 上是「模型默认」:一个思考配置都不发(pi 默认会发一个 MINIMAL)。
    assert.equal(step1.body.generationConfig?.thinkingConfig, undefined, JSON.stringify(step1.body.generationConfig));

    // 第二次请求:签名 A 原样挂在它那个 functionCall 上,工具结果按同一个 id 回去。
    const call = callPart(step2.body, "lookup_asset", "fc-lookup-1");
    assert.ok(call, `第二次请求里没有那次函数调用:${JSON.stringify(step2.body.contents)}`);
    assert.equal(call.thoughtSignature, SIG.A, "思考签名丢了 —— Gemini 3 会整轮 400");
    assert.deepEqual(call.functionCall.args, { asset_id: "asset-42" });
    const response = step2.body.contents.flatMap((content) => content.parts).find((part) => part.functionResponse);
    assert.equal(response.functionResponse.id, "fc-lookup-1");
    assert.equal(response.functionResponse.name, "lookup_asset");
    assert.match(response.functionResponse.response.output, /12s beach clip/);
    assert.deepEqual(toolCalls[0], ["lookup_asset", "fc-lookup-1", { asset_id: "asset-42" }]);

    // 用量按 Gemini 回报的记:输入扣掉缓存命中,思考计进输出,缓存命中单列。
    assert.equal(first.usage.input_tokens, 812 + (930 - 512));
    assert.equal(first.usage.output_tokens, 18 + 64 + 11);
    assert.equal(first.usage.cache_read_tokens, 512);
    assert.equal(first.usage.reasoning_tokens, 64);
    assert.equal(first.usage.requests, 2);

    // 第二轮:会话状态经后端存一遍(JSON 往返),顺序调两个工具。
    const second = await runPiTurn(
      {
        systemPrompt: "你是 Mosael 的智能体。",
        prompt: "再比一比哪个更长。",
        provider: geminiProvider(gemini.baseUrl),
        model: fixture.model,
        tools,
        apiBase: "http://127.0.0.1:1",
        token: "t",
        sessionState: JSON.parse(JSON.stringify(first.sessionState)),
        thinkingLevel: "high",
      },
      handlers(),
    );
    assert.equal(second.errorMessage, undefined, `第二轮失败:${second.errorMessage}`);
    assert.equal(second.text, "asset-7 is the longer one.");
    assert.equal(gemini.requests.length, 5);
    const [turn2step1, , turn2step3] = gemini.requests.slice(2);
    // 上一轮的签名在历史里一个没少:函数调用上的 A,回答末尾的 T1。
    assert.equal(callPart(turn2step1.body, "lookup_asset", "fc-lookup-1")?.thoughtSignature, SIG.A);
    assert.ok(
      modelParts(turn2step1.body).some((part) => part.thoughtSignature === SIG.T1 && /clip of a beach/.test(part.text ?? "")),
      "上一轮回答末尾的签名丢了",
    );
    // 顺序调用的每一步各带一个签名,第三次请求里两个都在。
    assert.equal(callPart(turn2step3.body, "list_assets", "fc-list-1")?.thoughtSignature, SIG.B);
    assert.equal(callPart(turn2step3.body, "lookup_asset", "fc-lookup-2")?.thoughtSignature, SIG.C);
    // 思考档位「高」→ Gemini 3 的 thinkingLevel。
    assert.deepEqual(turn2step1.body.generationConfig.thinkingConfig, { includeThoughts: true, thinkingLevel: "HIGH" });
  } finally {
    await gemini.close();
  }
});

/** 一段最短的文字回包。 */
const textReply = (text) => [
  {
    candidates: [{ content: { role: "model", parts: [{ text }] }, finishReason: "STOP", index: 0 }],
    usageMetadata: { promptTokenCount: 20, candidatesTokenCount: 3, totalTokenCount: 23 },
  },
];

async function gateway(baseUrl, model, extra = {}, apiKey = KEY) {
  return runGatewayCompletion({
    systemPrompt: "只回答正文",
    prompt: "写一句",
    provider: { ...geminiProvider(baseUrl, extra), apiKey },
    model,
    apiBase: "http://127.0.0.1:1",
    token: "",
    options: { temperature: 0.3, maxTokens: 256 },
  });
}

test("网关单次补全:2.5 Pro 关不掉思考,不发 thinkingBudget 0;2.5 Flash 关得掉,就发 0", async () => {
  const gemini = await fakeGemini([textReply("好。"), textReply("行。")]);
  try {
    const pro = await gateway(gemini.baseUrl, "gemini-2.5-pro");
    assert.equal(pro.text, "好。");
    assert.equal(gemini.requests[0].body.generationConfig.thinkingConfig, undefined, "2.5 Pro 发 thinkingBudget 0 会被拒");
    assert.equal(gemini.requests[0].body.generationConfig.maxOutputTokens, 256);

    await gateway(gemini.baseUrl, "gemini-2.5-flash", {
      thinkingLevelMap: { off: "off", low: "low", medium: "medium", high: "high" },
    });
    assert.deepEqual(gemini.requests[1].body.generationConfig.thinkingConfig, { thinkingBudget: 0 });
  } finally {
    await gemini.close();
  }
});

test("pi 目录里还没有的新型号照样调得通,按同一个协议发", async () => {
  const gemini = await fakeGemini([textReply("新的。")]);
  try {
    const result = await gateway(gemini.baseUrl, "gemini-3.9-flash");
    assert.equal(result.text, "新的。");
    assert.match(gemini.requests[0].url, /^\/v1beta\/models\/gemini-3\.9-flash:streamGenerateContent/);
    assert.equal(gemini.requests[0].headers["x-goog-api-key"], KEY);
  } finally {
    await gemini.close();
  }
});

test("钥匙空着就当场报错,不去用环境变量里别人的钥匙", async () => {
  const gemini = await fakeGemini([textReply("不该到这里")]);
  try {
    await assert.rejects(() => gateway(gemini.baseUrl, "gemini-2.5-flash", {}, ""), /API Key/);
    assert.equal(gemini.requests.length, 0, "一个请求都不该发出去");
  } finally {
    await gemini.close();
  }
});
