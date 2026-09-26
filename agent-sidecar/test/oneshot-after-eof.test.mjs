/**
 * 一次性的请求(补全、压缩、刷新凭据):后端写一帧就关 stdin,结果只从 stdout 回。
 *
 * 此前读循环一读到 stdin 关闭就 `process.exit(0)` —— 那一刻模型请求还在路上,结果永远送不回来;后端
 * 只拿到 stderr 里那几行启动日志,当成报错原样甩给用户(画板「写不出来:[sidecar] outbound proxy enabled…
 * stdin closed; exiting」)。自 1.4.3 起每一次走 sidecar 的补全都是这样。
 *
 * 这里驱动**打包产物**、走真的 stdin/stdout:一台过 400ms 才回话的假供应商,写完帧立刻关 stdin ——
 * 和后端 adapters.run_gateway 一模一样。要看到的是:结果帧回来了,然后进程自己退了。
 *
 * 跑法:node agent-sidecar/test/oneshot-after-eof.test.mjs
 */
import { spawn } from "node:child_process";
import assert from "node:assert/strict";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

let hits = 0;
const slow = http.createServer((req, res) => {
  hits += 1;
  req.resume();
  setTimeout(() => {
    res.writeHead(500, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: { message: "slow supplier says no" } }));
  }, 400);
});
await new Promise((resolve) => slow.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${slow.address().port}`;

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
      /* 非协议行 */
    }
  }
});
const exited = new Promise((resolve) => child.on("exit", (code) => resolve(code)));

child.stdin.write(JSON.stringify({
  type: "gateway_complete",
  turnId: "gateway",
  systemPrompt: "只给正文",
  prompt: "写一句",
  images: [],
  provider: { baseUrl: `${base}/v1`, apiKey: "k", vendor: "openai" },
  model: "m",
  apiBase: "http://127.0.0.1:1",
  token: "ephemeral",
  options: {},
}) + "\n");
child.stdin.end();

const timer = setTimeout(() => {
  child.kill("SIGKILL");
}, 15000);
const code = await exited;
clearTimeout(timer);
slow.close();

assert.equal(hits > 0, true, "请求根本没发到供应商 —— 进程在发出去之前就退了");
const answer = events.find((e) => e.turnId === "gateway" && (e.type === "error" || e.type === "gateway_done"));
assert.ok(answer, `stdin 关了之后没把结果送回来就退了;收到的是 ${JSON.stringify(events)}`);
assert.equal(code, 0, "送完结果之后该自己退(退出码 0)");
console.log("oneshot-after-eof: ok");
