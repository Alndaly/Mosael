// SubagentManager:非阻塞派发的记录簿。钉住的是**通知去重**语义 ——
// wait_subagents 已经把报告带进上下文的,收尾清算(drain)不能再送一遍;
// 没进过上下文的,drain 必须一个不落地送到。送重了模型会把同一份报告消化两次,
// 送丢了报告永远到不了模型(sidecar 是回合级进程,这轮不送就没了)。
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { buildSync } from "esbuild";

const outDir = mkdtempSync(join(tmpdir(), "subagent-manager-"));
const outFile = join(outDir, "subagent.mjs");
buildSync({
  entryPoints: [new URL("../src/subagent.ts", import.meta.url).pathname],
  bundle: true,
  format: "esm",
  platform: "node",
  outfile: outFile,
  // 只测 SubagentManager,pi 的包不用真打进来 —— 打了反而要装它的原生依赖。
  external: ["@earendil-works/pi-agent-core", "@earendil-works/pi-ai"],
});
// external 的 import 在测试环境解析不到也无妨:类本身不用它们。给个空壳。
const stub = join(outDir, "node_modules", "@earendil-works");
for (const name of ["pi-agent-core", "pi-ai"]) {
  mkdirSync(join(stub, name), { recursive: true });
  writeFileSync(join(stub, name, "package.json"), JSON.stringify({ name: `@earendil-works/${name}`, main: "index.js" }));
  writeFileSync(join(stub, name, "index.js"), "export {};\nexport class Agent {}\n");
}
const { SubagentManager } = await import(pathToFileURL(outFile).href);

const outcome = (report) => ({ report, steps: 1, trace: [] });

test("wait 过的不再进收尾清算,没 wait 过的一个不落", async () => {
  const manager = new SubagentManager();
  manager.dispatch("a", "任务A", Promise.resolve(outcome("报告A")));
  manager.dispatch("b", "任务B", Promise.resolve(outcome("报告B")));

  // 模型只等了 a —— a 的报告已进上下文
  const waited = await manager.wait(["a"]);
  assert.equal(waited.length, 1);
  assert.equal(waited[0].id, "a");
  assert.equal(waited[0].outcome.report, "报告A");

  // 收尾:只剩 b 需要送;再清一次必须是空(不重复通知)
  const settled = await manager.drain();
  assert.deepEqual(settled.map((s) => s.id), ["b"]);
  assert.equal((await manager.drain()).length, 0);
});

test("无参 wait 等全部,之后 drain 为空", async () => {
  const manager = new SubagentManager();
  manager.dispatch("a", "任务A", Promise.resolve(outcome("A")));
  manager.dispatch("b", "任务B", Promise.resolve(outcome("B")));
  const waited = await manager.wait();
  assert.deepEqual(waited.map((s) => s.id).sort(), ["a", "b"]);
  assert.equal((await manager.drain()).length, 0);
});

test("drain 等未完成的跑完再返回", async () => {
  const manager = new SubagentManager();
  let release;
  manager.dispatch("slow", "慢任务", new Promise((resolve) => (release = () => resolve(outcome("慢报告")))));
  const draining = manager.drain();
  release();
  const settled = await draining;
  assert.equal(settled[0].outcome.report, "慢报告");
});
