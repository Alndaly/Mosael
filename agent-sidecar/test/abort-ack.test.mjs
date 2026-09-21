/**
 * 按「停止」要有回执,而且一轮刚开始那几百毫秒里按下去也得算数。
 *
 * 两个毛病在同一处:
 *
 * 1. `abort` 帧**连回执都没有**。`active.get(turnId)?.abort()` —— 拿不到就一声不吭,
 *    而后端把「管道写成功」当成「停住了」,界面显示已停止,那一轮继续跑到底。
 * 2. `active` 要到 `onAgentReady` 才写,而那发生在 `await buildAllTools(...)`(一次 HTTP)
 *    之后。**所以一轮刚开始那几百毫秒里按停止,按了等于没按。**
 *
 * 这里驱动的是**打包产物**,走真实的 stdin/stdout 协议 —— 这两件事都在 index.ts 的分发循环
 * 里,只有整条跑起来才证明得了。
 *
 * 跑法:node agent-sidecar/test/abort-ack.test.mjs
 */
import { spawn } from "node:child_process";
import assert from "node:assert/strict";
import http from "node:http";
import { fileURLToPath } from "node:url";
import path from "node:path";

// 一台**接了连接但永不回应**的服务器。`buildAllTools()` 会去拉工具清单,于是这一轮会
// 一直停在「已派发、Agent 还没就绪」这个状态上 —— 正是要测的那个窗口,被确定性地撑开。
//
// 第一版让它连到 9 号端口(必然 ECONNREFUSED),那样窗口窄到不可预测:单跑能过,
// 跟在别的测试后面跑就挂,因为那一轮在 abort 帧被读到之前就已经失败结束了。
// **一条时快时慢的测试,和没有测试一样**:它红的时候没人知道是代码还是运气。
const hanging = http.createServer(() => {});
await new Promise((resolve) => hanging.listen(0, "127.0.0.1", resolve));
const hangingUrl = `http://127.0.0.1:${hanging.address().port}`;

const here = path.dirname(fileURLToPath(import.meta.url));
const bundle = path.join(here, "..", "dist", "sidecar.cjs");

const child = spawn(process.execPath, [bundle], { stdio: ["pipe", "pipe", "pipe"] });
const events = [];
let buffer = "";
child.stdout.on("data", (chunk) => {
  buffer += chunk;
  const lines = buffer.split("\n");
  buffer = lines.pop() ?? "";
  for (const line of lines) {
    try {
      events.push(JSON.parse(line));
    } catch {
      /* 非协议行(日志)忽略 */
    }
  }
});

const send = (frame) => child.stdin.write(JSON.stringify(frame) + "\n");
const waitFor = (predicate, label, timeout = 8000) =>
  new Promise((resolve, reject) => {
    const started = Date.now();
    const tick = setInterval(() => {
      const hit = events.find(predicate);
      if (hit) {
        clearInterval(tick);
        resolve(hit);
      } else if (Date.now() - started > timeout) {
        clearInterval(tick);
        reject(new Error(`等不到${label};收到的是 ${JSON.stringify(events)}`));
      }
    }, 20);
  });

// ① 停一轮根本不存在的:回执要说「没接住」——「按晚了」不是错误,界面上不该报。
send({ type: "abort", turnId: "ghost" });
const ghost = await waitFor((e) => e.type === "aborted_ack" && e.turnId === "ghost", "ghost 的回执");
assert.equal(ghost.accepted, false, "不存在的轮次却说停住了");

// ② 派一轮出去,**立刻**按停止 —— 此刻 Agent 几乎肯定还没就绪(buildAllTools 要打一次 HTTP,
//    这里拉工具清单会永远挂住,所以这个窗口是确定开着的)。
send({
  type: "run_turn",
  turnId: "early",
  prompt: "hi",
  systemPrompt: "abort race",
  provider: { baseUrl: `${hangingUrl}/v1`, apiKey: "k" },
  model: "m",
  apiBase: hangingUrl,
  token: "t",
  workspaceId: "w",
  sessionId: "s",
});
send({ type: "abort", turnId: "early" });

const early = await waitFor((e) => e.type === "aborted_ack" && e.turnId === "early", "early 的回执");
assert.equal(early.accepted, true, "那一轮明明还在,却回了「没有东西可停」—— 按了等于没按");

child.kill();
hanging.close();
console.log("PASS  停止有回执,且一轮刚开始时按下去也算数");
