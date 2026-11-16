/**
 * 一轮**没说完就结束**的时候,不能看起来像正常说完了。
 *
 * 用户截图(Kimi · k3):「我先看看现在的状态:视频素材还在不在、项目里有没有时间线、画板列表是否恢复了:」到此为止,
 * 没有工具调用、没有错误,输入框已经可以发 —— 一轮像是正常结束了。pi 在三种情况下会这样安静地收尾:
 *
 *   · stopReason=length(输出额度用完)且这条回复里还没开始写工具调用:pi 的循环没有工具可跑,就此结束。
 *     此前只在正文不到 24 个字时才报「用完输出额度」,正文长一点就当成功 —— 截断被吞了;
 *   · stopReason=toolUse(finish_reason=tool_calls)却一个工具调用都没解析出来:同样没有工具可跑,就此结束;
 *   · Anthropic 协议的 pause_turn:供应商说「先停一下,重发接着来」,pi 把它当成 stop。
 *
 * 处理:这三种先**自动续一次**(给模型一句说明,让它从断处接着做);续完还是这样,就报错 —— 对话里一定有一行
 * 说清楚发生了什么,而不是停在一个冒号上。正常 stop 一次都不续。
 *
 * 驱动的是真的 runPiTurn,拦的是 fetch:供应商的每次回应按脚本给(OpenAI 兼容的 SSE 流)。
 */
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const outdir = path.join(import.meta.dirname, "..", "dist");
mkdirSync(outdir, { recursive: true });
const outfile = path.join(outdir, "pi.turn-ends.mjs");
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

/** 一次回应:先吐正文,再(可选)吐工具调用,最后给 finish_reason。 */
function sse({ text = "", toolCalls = [], finish = "stop", promptTokens = 100 }) {
  const chunk = (delta, finishReason = null, usage) =>
    `data: ${JSON.stringify({
      id: "c",
      object: "chat.completion.chunk",
      created: 0,
      model: "m",
      choices: [{ index: 0, delta, finish_reason: finishReason }],
      ...(usage ? { usage } : {}),
    })}\n\n`;
  let body = chunk({ role: "assistant" });
  if (text) body += chunk({ content: text });
  toolCalls.forEach((call, index) => {
    body += chunk({ tool_calls: [{ index, id: call.id, type: "function", function: { name: call.name, arguments: call.arguments } }] });
  });
  body += chunk({}, finish, { prompt_tokens: promptTokens, completion_tokens: 20, total_tokens: promptTokens + 20 });
  body += "data: [DONE]\n\n";
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

/** 跑一轮;`script` 是供应商依次给出的回应。返回结果和每次请求的 body。 */
async function turn(script, { tools = [], provider = {} } = {}) {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (_url, init) => {
    requests.push(JSON.parse(String(init.body)));
    const next = script[Math.min(requests.length - 1, script.length - 1)];
    return sse(next);
  };
  const deltas = [];
  try {
    const result = await runPiTurn(
      {
        systemPrompt: "s",
        prompt: "请你重新创建对应时间线",
        provider: { baseUrl: "https://api.example.com/v1", apiKey: "k", vendor: "openai-compatible", contextWindow: 128000, maxOutputTokens: 8192, ...provider },
        model: "m",
        tools,
        apiBase: "http://127.0.0.1:1",
        token: "t",
        thinkingLevel: "off",
      },
      {
        onDelta: (delta) => deltas.push(delta),
        onThinking: () => {},
        onThinkingEnd: () => {},
        onToolStart: () => {},
        onToolEnd: () => {},
      },
    );
    return { result, requests, text: deltas.join("") };
  } finally {
    globalThis.fetch = original;
  }
}

const lastUserText = (body) => {
  const users = body.messages.filter((m) => m.role === "user");
  const content = users.at(-1)?.content;
  return typeof content === "string" ? content : JSON.stringify(content);
};

const COLON = "我先看看现在的状态:视频素材还在不在、项目里有没有时间线、画板列表是否恢复了:";

test("正常 stop:一次请求,不续,不报错", async () => {
  const { result, requests } = await turn([{ text: "好的,已经建好了。", finish: "stop" }]);
  assert.equal(requests.length, 1);
  assert.equal(result.errorMessage, undefined);
});

test("length 截断、正文已经很长:自动续一次,续上的正文接在后面,不算失败", async () => {
  const { result, requests, text } = await turn([
    { text: COLON, finish: "length" },
    { text: "素材都在,时间线也在。", finish: "stop" },
  ]);
  assert.equal(requests.length, 2, "截断之后没有续");
  assert.match(lastUserText(requests[1]), /截断/, "续的那一次要告诉模型它被截断了");
  assert.equal(text, `${COLON}素材都在,时间线也在。`);
  assert.equal(result.errorMessage, undefined);
});

test("续了一次还是 length:报 output_limit —— 不能停在冒号上假装说完了", async () => {
  const { result, requests } = await turn([
    { text: COLON, finish: "length" },
    { text: "素材都在,", finish: "length" },
  ]);
  assert.equal(requests.length, 2, "只续一次");
  assert.equal(result.errorCode, "output_limit");
  assert.ok(result.errorMessage, "截断被吞了:没有错误");
});

test("finish_reason=tool_calls 却没有工具调用:让模型重发一次;重发成了就照常跑完", async () => {
  const tool = {
    name: "list_assets",
    label: "列出素材",
    description: "列",
    parameters: { type: "object", properties: {} },
    execute: async () => ({ content: [{ type: "text", text: "[]" }], details: {} }),
  };
  const { result, requests } = await turn(
    [
      { text: COLON, finish: "tool_calls" },
      { toolCalls: [{ id: "call-1", name: "list_assets", arguments: "{}" }], finish: "tool_calls" },
      { text: "素材都在。", finish: "stop" },
    ],
    { tools: [tool] },
  );
  assert.equal(requests.length, 3);
  assert.match(lastUserText(requests[1]), /工具调用/, "要告诉模型它的工具调用没有到");
  assert.equal(result.errorMessage, undefined);
});

test("重发之后还是没有工具调用:报错,说清楚是工具调用丢了", async () => {
  const { result, requests } = await turn([
    { text: COLON, finish: "tool_calls" },
    { text: "马上检查现状:", finish: "tool_calls" },
  ]);
  assert.equal(requests.length, 2);
  assert.equal(result.errorCode, "tool_call_lost");
  assert.ok(result.errorMessage);
});

test("停在冒号上的正常 stop:续一次(它多半是要接着调工具或列内容);续完就照常结束", async () => {
  /* 用户截图里三轮都停在冒号上:「需要你帮一个小忙:」「…画板列表是否恢复了:」「没卡住,马上检查现状:」。
     供应商说的是正常结束(或者我们不知道它说了什么),但一句话停在冒号上几乎从来不是说完了。 */
  const tool = {
    name: "list_assets",
    label: "列出素材",
    description: "列",
    parameters: { type: "object", properties: {} },
    execute: async () => ({ content: [{ type: "text", text: "[]" }], details: {} }),
  };
  const { result, requests } = await turn(
    [
      { text: "没卡住,马上检查现状:", finish: "stop" },
      { toolCalls: [{ id: "call-1", name: "list_assets", arguments: "{}" }], finish: "tool_calls" },
      { text: "素材都在。", finish: "stop" },
    ],
    { tools: [tool] },
  );
  assert.equal(requests.length, 3, "停在冒号上没有续");
  assert.match(lastUserText(requests[1]), /冒号/);
  assert.equal(result.errorMessage, undefined);
});

test("续完还停在冒号上:就当它说完了,不报错 —— 那是模型的决定,不是丢了东西", async () => {
  const { result, requests } = await turn([
    { text: "需要你帮一个小忙:", finish: "stop" },
    { text: "请把原视频重新导入一次:", finish: "stop" },
  ]);
  assert.equal(requests.length, 2, "只续一次");
  assert.equal(result.errorMessage, undefined);
});
