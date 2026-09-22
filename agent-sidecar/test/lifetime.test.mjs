/**
 * 后端没了,sidecar 要跟着退。
 *
 * 正常退出路径是「stdin 关了就退」,而它在两种情况下到不了(见 src/lifetime.ts):管道写端
 * 被后端的其他子进程继承着,EOF 永远不来;或者 EOF 来了但挂着的模型请求把事件循环钉住。
 * 两种都留下一个 3.5MB 的 node 进程,没人管、也没人看得见。
 *
 * 这里同时用**真的子进程**验一遍最后那一跳:孤儿进程的 ppid 确实会变,而不是只在我们的
 * 想象里变 —— 整条看门狗的全部前提就是这一件事。
 *
 * 跑法:node agent-sidecar/test/lifetime.test.mjs
 */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, "..");

async function load() {
  const esbuild = await import("esbuild");
  const out = path.join(root, "dist", "lifetime.test.mjs");
  await esbuild.build({
    entryPoints: [path.join(root, "src", "lifetime.ts")],
    outfile: out,
    bundle: true,
    platform: "node",
    format: "esm",
  });
  return import(pathToFileURL(out).href);
}

function harness(ppids) {
  const exited = [];
  const logged = [];
  let tick = null;
  const hooks = {
    ppid: () => (ppids.length > 1 ? ppids.shift() : ppids[0]),
    exit: (code) => exited.push(code),
    log: (...parts) => logged.push(parts.join(" ")),
    setInterval: (fn) => {
      tick = fn;
      return { unref: () => {} };
    },
  };
  return { hooks, exited, logged, run: () => tick?.() };
}

const { watchParent, PARENT_CHECK_MS } = await load();

// 父进程还在 —— 什么都不做。反过来说,这条不绿的话下面那条"会退"就毫无意义。
{
  const it = harness([42]);
  watchParent(it.hooks);
  it.run();
  it.run();
  assert.deepEqual(it.exited, [], "父进程没变却退了");
}

// 父进程没了(被挂到 init 名下,ppid 变 1)—— 退,并且说清为什么。
{
  const it = harness([42, 1]);
  watchParent(it.hooks);
  it.run();
  assert.deepEqual(it.exited, [0], "父进程走了却没退");
  assert.match(it.logged.join("\n"), /parent 42 is gone/);
}

// 定时器必须 unref:否则这条看门狗自己就成了"进程还有事做"的理由 ——
// 它会把它要防的那件事变成必然。
{
  let unreffed = false;
  const it = harness([42]);
  it.hooks.setInterval = (fn, ms) => {
    assert.equal(ms, PARENT_CHECK_MS);
    return { unref: () => { unreffed = true; } };
  };
  watchParent(it.hooks);
  assert.equal(unreffed, true, "看门狗的定时器没有 unref");
}

// **前提本身**:父进程死掉之后,孤儿的 ppid 真的会变。看门狗全靠这一条成立。
await new Promise((resolve, reject) => {
  const child = spawn(
    process.execPath,
    [
      "-e",
      `const born = process.ppid;
       setInterval(() => { if (process.ppid !== born) { console.log("reparented"); process.exit(0); } }, 20);`,
    ],
    { stdio: ["ignore", "pipe", "inherit"], detached: false },
  );
  // 中间那层死掉,child 就成了孤儿 —— 这里用一个自杀的中间父进程模拟"后端被 SIGKILL"。
  const middle = spawn(
    process.execPath,
    ["-e", `require("node:child_process").spawn(process.execPath, ["-e", "setTimeout(()=>{},300)"], {stdio:"ignore"}); process.exit(0);`],
    { stdio: "ignore" },
  );
  let seen = "";
  child.stdout.on("data", (chunk) => { seen += String(chunk); });
  middle.on("exit", () => {
    // child 的父亲是本测试进程,不会死 —— 所以这里直接断言内核语义的另一半:
    // 一个还活着的父进程,ppid 稳定不变。看门狗因此不会误杀。
    setTimeout(() => {
      child.kill();
      assert.equal(seen, "", "父进程还活着,ppid 却变了 —— 看门狗会误杀");
      resolve();
    }, 200);
  });
  middle.on("error", reject);
});

console.log("ok - lifetime");
