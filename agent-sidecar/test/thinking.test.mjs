/**
 * 思考开关必须真的接线。
 *
 * 曾经的状态:model.reasoning 默认 false,而 pi 里每一条"把思考关掉"的分支都写着
 * `&& model.reasoning` —— 于是会话里的思考档位两个方向都发不出去,DeepSeek 这类混合模型
 * 无论开关都在思考。类型全绿、单测全绿,因为两边都在自说自话。
 */
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

// 产物必须落在 agent-sidecar 里面(dist/ 已被 .gitignore 忽略):放临时目录的话
// node 从那儿解析不到 @earendil-works/*,而把依赖整个打进来又会撞上 pi 依赖链里的
// CJS 动态 require。留在包内 + packages:"external" 两个问题都没有。
const outdir = path.join(import.meta.dirname, "..", "dist");
mkdirSync(outdir, { recursive: true });
const outfile = path.join(outdir, "pi.test.mjs");
await build({
  entryPoints: [path.join(import.meta.dirname, "..", "src", "pi.ts")],
  outfile,
  format: "esm",
  bundle: true,
  platform: "node",
  packages: "external",
  ignoreAnnotations: true,
});
const { buildModels } = await import(pathToFileURL(outfile).href);
const source = await readFile(path.join(import.meta.dirname, "..", "src", "pi.ts"), "utf8");

test("reasoning 默认开 —— 否则思考档位两个方向都发不出去", () => {
  const { model } = buildModels("https://api.deepseek.com", "k", "deepseek-v4-pro");
  assert.equal(model.reasoning, true);
});

test("reasoning_effort 仍然默认关 —— 通用端点不认它会直接 400", () => {
  // 这是 reasoning 默认开之所以安全的原因:关掉思考的分支按 baseUrl 匹配到具体供应商,
  // 通用 OpenAI 兼容端点走的最后两条分支额外要求 supportsReasoningEffort。
  const { model } = buildModels("http://localhost:11434/v1", "", "gemma4");
  assert.equal(model.compat.supportsReasoningEffort, false);
  assert.equal(model.compat.supportsDeveloperRole, false);
});

test("用户显式关掉推理模型时照办", () => {
  const { model } = buildModels("https://api.deepseek.com", "k", "m", { reasoning: false });
  assert.equal(model.reasoning, false);
});

test("模型目录给出 1M 时原样采用，不被通用回退值压低", () => {
  const { model } = buildModels("https://api.example.com/v1", "k", "advanced", {
    contextWindow: 1_000_000,
    maxOutputTokens: 64_000,
  });
  assert.equal(model.contextWindow, 1_000_000);
  assert.equal(model.maxTokens, 64_000);
});

test("无效的零窗口不覆盖云端 128K 回退", () => {
  const { model } = buildModels("https://api.example.com/v1", "k", "unknown", {
    contextWindow: 0,
  });
  assert.equal(model.contextWindow, 128_000);
});

test("必须走 streamSimple —— 思考档位的翻译只发生在它里面", () => {
  // pi 的 Agent 把档位放在 options.reasoning,而拼请求体的地方读 options.reasoningEffort;
  // 两者之间的翻译(含按模型 clamp)只在 streamSimple 里。走 stream 的话 reasoningEffort
  // 永远 undefined,供应商收到的永远是"别思考" —— 档位调什么都没用,而类型全绿。
  assert.ok(source.includes("models.streamSimple("), "streamFn 必须调 models.streamSimple");
  assert.ok(!/[^e]models\.stream\(/.test(source), "不得再有裸的 models.stream( 调用");
});
