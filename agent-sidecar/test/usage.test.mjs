/**
 * `collectUsage` 的判据。
 *
 * 它决定后端是记**真实 token 用量**还是退回按字符数估算 —— 而估算值会直接进用量图表和费用统计。
 * 三条容易写错、且错了不会有人立刻发现的地方:
 *   1. 一轮可能有多条助手消息(每次工具调用都会触发后续 LLM 调用),必须累加而不是取最后一条;
 *   2. 一条都没读到时**不能硬报 0** —— 那会让后端以为拿到了真实用量而跳过估算,费用恒为 0,
 *      比估算更糟;
 *   3. cacheRead/cacheWrite 不能压平进 input:它们计价不同,压平会让费用偏高。
 *
 * 跑法:node agent-sidecar/test/usage.test.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// 从打包产物里取实现,和真正跑的是同一份代码(源码是 TS,这里不引 ts 运行时)。
const here = path.dirname(fileURLToPath(import.meta.url));
const bundle = readFileSync(path.join(here, "..", "dist", "sidecar.cjs"), "utf-8");
const match = bundle.match(/function collectUsage\(messages, startIndex[^)]*\) \{[\s\S]*?\n\}/);
assert.ok(match, "打包产物里找不到 collectUsage —— 是不是被改名或内联了?");
const collectUsage = new Function(`${match[0]}; return collectUsage;`)();

const assistant = (usage) => ({ role: "assistant", usage });

// 1) 多条助手消息累加
{
  const out = collectUsage([
    assistant({ input: 100, output: 20, cacheRead: 0, cacheWrite: 0 }),
    { role: "user" },
    assistant({ input: 300, output: 50, cacheRead: 0, cacheWrite: 0 }),
  ]);
  assert.equal(out.input_tokens, 400, "多条助手消息应当累加 input");
  assert.equal(out.output_tokens, 70);
  assert.equal(out.total_tokens, 470);
  assert.equal(out.requests, 2);
}

// 2) 没有可用用量时退回 { requests: 1 },让后端去估算
{
  const out = collectUsage([{ role: "user" }, { role: "assistant" }]);
  assert.deepEqual(out, { requests: 1 }, "读不到用量时必须退回估算,不能硬报 0");
  assert.equal(out.input_tokens, undefined);
}

// 3) 缓存 token 单独记,不并进 input
{
  const out = collectUsage([assistant({ input: 10, output: 5, cacheRead: 900, cacheWrite: 40 })]);
  assert.equal(out.input_tokens, 10, "cacheRead 不能被并进 input(计价不同)");
  assert.equal(out.cache_read_tokens, 900);
  assert.equal(out.cache_write_tokens, 40);
}

// 4) 非助手消息不计入(工具结果也可能带 usage)
{
  const out = collectUsage([{ role: "tool", usage: { input: 999, output: 999 } }]);
  assert.deepEqual(out, { requests: 1 }, "非助手消息的 usage 不该被计入本轮");
}

// 5) 历史消息只用于上下文，不能重复记到本轮账单里
{
  const out = collectUsage(
    [
      assistant({ input: 10_000, output: 500 }),
      { role: "user" },
      assistant({ input: 300, output: 50 }),
    ],
    2,
  );
  assert.equal(out.input_tokens, 300, "本轮用量不能累计历史 assistant 的 usage");
  assert.equal(out.output_tokens, 50);
  assert.equal(out.requests, 1);
}

console.log("PASS  collectUsage 5 组断言全过");
