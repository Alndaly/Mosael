#!/usr/bin/env node
/**
 * `pnpm dev` 开跑之前先看一眼端口。
 *
 * 踩过两次:上次退出的后端还占着 8800,这次 `uvicorn` 起不来(`[Errno 48] Address already in use`),
 * `concurrently -k` 于是把 vite / electron 一起带走 —— 屏幕上看起来像"App 莫名退出",
 * 真正的原因埋在几十行日志中间。这里在开头就说清楚:端口是谁占的、怎么清、或者换个端口。
 *
 * 判"有没有人在听"用 TCP 连一下,不用 `lsof`:lsof 在有些 PATH 下找不到,
 * 而"找不到就当端口空着"是这里最危险的失败方式(检查通过、启动照旧失败)。PID 只用来补充说明。
 */

import { execFileSync } from "node:child_process";
import { connect } from "node:net";

const BACKEND_PORT = process.env.MOSAEL_BACKEND_PORT || "8800";
const VITE_PORT = "5173";

/** 连得上就是有人在听。 */
function listening(port) {
  return new Promise((resolve) => {
    const socket = connect({ host: "127.0.0.1", port: Number(port) });
    const done = (answer) => {
      socket.destroy();
      resolve(answer);
    };
    socket.setTimeout(600);
    socket.once("connect", () => done(true));
    socket.once("timeout", () => done(false));
    socket.once("error", () => done(false));
  });
}

/** 谁在听(拿不到就算了,只说端口). */
function listeners(port) {
  try {
    return execFileSync("lsof", ["-nP", `-iTCP:${port}`, "-sTCP:LISTEN", "-t"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    })
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  } catch {
    return [];
  }
}

function commandOf(pid) {
  try {
    return execFileSync("ps", ["-p", pid, "-o", "command="], { encoding: "utf8" }).trim();
  } catch {
    return "";
  }
}

const problems = [];
for (const [name, port] of [
  ["桌面后端", BACKEND_PORT],
  ["vite", VITE_PORT],
]) {
  if (await listening(port)) problems.push({ name, port });
}

if (problems.length === 0) process.exit(0);

console.error("\n开不了:下面这些端口已经有进程在听了(多半是上次没退干净的后端 / 前端)。\n");
for (const { name, port } of problems) {
  console.error(`  ${name} :${port}`);
  for (const pid of listeners(port)) {
    const command = commandOf(pid);
    console.error(`    pid ${pid}${command ? `  ${command.slice(0, 110)}` : ""}`);
  }
}
const ports = problems.map((problem) => problem.port).join("|");
console.error(`
清掉再试:
  lsof -ti:${ports} | xargs kill

或者换一个后端端口(前端会自动跟上):
  MOSAEL_BACKEND_PORT=8801 pnpm dev
`);
process.exit(1);
