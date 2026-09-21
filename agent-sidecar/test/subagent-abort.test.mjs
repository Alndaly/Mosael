// 用户按「停止」时,后台子智能体也要停下来。
//
// 这条钉的是**一个一直都在、却从来没被接上的参数**:`runSubagent` 的输入类型里声明了
// `signal?: AbortSignal`,pi.ts 派发时也老老实实传了 —— 而函数体里 `input.signal` 出现 0 次。
// TypeScript 不会说什么,因为它是可选的;四层俱全,最后一环没接上。
//
// 后果不是"子智能体多跑一会儿"。子智能体是一整个 agent 循环,没有自己的时限,它的 promise
// 挂在 Node 的事件循环上 → `main()` 返回了进程也不退 → 后端 `finish()` 等不到它 →
// 「把会话拨回 idle」那段永远执行不到 → **界面上那个会话永远停在「思考中」**,
// 之后每条消息都被拒绝且不报错(和 backend/tests/test_sidecar_backpressure.py 同一个症状)。
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { buildSync } from "esbuild";

const outDir = mkdtempSync(join(tmpdir(), "subagent-abort-"));
const outFile = join(outDir, "subagent.mjs");
buildSync({
  entryPoints: [fileURLToPath(new URL("../src/subagent.ts", import.meta.url))],
  bundle: true,
  format: "esm",
  platform: "node",
  outfile: outFile,
  external: ["@earendil-works/pi-agent-core", "@earendil-works/pi-ai"],
});

// 假的 Agent:`prompt()` 永远不自己结束,只有 `abort()` 能了结它 —— 正是真实子智能体的形状
// (一个没有时限的循环)。它同时记下 abort 被调用过没有。
const stub = join(outDir, "node_modules", "@earendil-works");
for (const name of ["pi-agent-core", "pi-ai"]) {
  mkdirSync(join(stub, name), { recursive: true });
  writeFileSync(join(stub, name, "package.json"), JSON.stringify({ name: `@earendil-works/${name}`, main: "index.js" }));
}
writeFileSync(join(stub, "pi-ai", "index.js"), "export {};\n");
writeFileSync(
  join(stub, "pi-agent-core", "index.js"),
  `export const aborts = { count: 0 };
export class Agent {
  constructor(options) { this.options = options; this.state = { messages: [] }; this._reject = null; }
  subscribe() { return () => {}; }
  abort() { aborts.count += 1; this._reject?.(new Error("aborted")); }
  prompt() { return new Promise((_resolve, reject) => { this._reject = reject; }); }
}
`,
);
const { runSubagent } = await import(pathToFileURL(outFile).href);
const { aborts } = await import(pathToFileURL(join(stub, "pi-agent-core", "index.js")).href);

const input = (signal) => ({ task: "看一遍这 40 个素材", tools: [], model: {}, streamFn: {}, signal });

test("父轮中止时,在跑的子智能体跟着停 —— 而不是把 promise 留在事件循环上", async () => {
  const controller = new AbortController();
  const running = runSubagent(input(controller.signal));

  // 还没中止:它就该一直跑着。用一个宏任务确认它确实没有自己结束。
  const pending = await Promise.race([running.then(() => "settled"), new Promise((r) => setTimeout(() => r("still running"), 20))]);
  assert.equal(pending, "still running", "子智能体本该一直跑 —— 测试的前提没成立");

  controller.abort();
  const result = await running;

  assert.equal(aborts.count, 1, "父轮中止了,而子智能体的 abort() 没被调用 —— 信号没接上");
  assert.ok(result.error, "停下来的子智能体要带着原因回来,不能装作出了结论");
});

test("信号在派发前就已经中止的,连跑都不跑", async () => {
  const before = aborts.count;
  const controller = new AbortController();
  controller.abort();

  const result = await runSubagent(input(controller.signal));

  assert.equal(aborts.count, before, "已经中止了还去起一个 agent 循环");
  assert.match(result.error ?? "", /中止/);
});

test("没有信号也要能跑 —— signal 是可选的", async () => {
  const running = runSubagent(input(undefined));
  const pending = await Promise.race([running.then(() => "settled"), new Promise((r) => setTimeout(() => r("still running"), 20))]);
  assert.equal(pending, "still running");
});
