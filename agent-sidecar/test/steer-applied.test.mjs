/**
 * steer 不是「发出去」就算生效：pi 真正把它放进模型上下文时，sidecar 必须把稳定 id 回传给 Mosael。
 *
 * 这条用真的 pi Agent 跑：`onAgentReady` 里排一条带 `mosaelSteerId` 的 steer，下一轮 loop
 * 发出 message_start 时必须命中同一条 id。类型和队列都绿、但属性被复制丢掉时，这条会红。
 */
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const root = path.join(import.meta.dirname, "..");
const outdir = path.join(root, "dist");
mkdirSync(outdir, { recursive: true });
const outfile = path.join(outdir, "steer-applied.test-bundle.mjs");
await build({
  entryPoints: [path.join(root, "src", "pi.ts")],
  outfile,
  format: "esm",
  bundle: true,
  platform: "node",
  packages: "external",
  ignoreAnnotations: true,
});
const { runPiTurn } = await import(pathToFileURL(outfile).href);

test("steer 进入模型上下文时回传稳定 steerId", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response("nope", { status: 500, statusText: "stubbed" });
  const applied = [];
  try {
    await runPiTurn(
      {
        systemPrompt: "s",
        prompt: "先做这一步",
        provider: { baseUrl: "https://api.deepseek.com", apiKey: "k", vendor: "deepseek" },
        model: "deepseek-v4-flash",
        tools: [],
        apiBase: "http://127.0.0.1:1",
        token: "t",
        thinkingLevel: "off",
        onAgentReady: (agent) => {
          agent.steer({
            role: "user",
            content: "改成竖屏",
            timestamp: Date.now(),
            mosaelSteerId: "queued-message-1",
          });
        },
      },
      {
        onDelta: () => {},
        onThinking: () => {},
        onThinkingEnd: () => {},
        onToolStart: () => {},
        onToolEnd: () => {},
        onSteerApplied: (steerId) => applied.push(steerId),
      },
    );
  } catch {
    // 供应商 500 是故意的：边界事件在真正请求模型之前就该发出。
  } finally {
    globalThis.fetch = original;
  }
  assert.deepEqual(applied, ["queued-message-1"]);
});
