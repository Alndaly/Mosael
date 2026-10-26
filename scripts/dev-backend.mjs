#!/usr/bin/env node
/**
 * 开发环境的后端启动器。
 *
 * 桌面版会把 `<数据目录>/secret.key` 封进系统钥匙串、删掉明文；此后 `pnpm dev` 里独立启动的后端拿不到钥匙，
 * 按设计会拒绝启动（另生一把会让已存凭据全部解不开）。这里在启动 uvicorn 之前用已有的
 * `scripts/print-master-key.cjs` 解出同一把钥匙，只交给这个后端进程。
 *
 * 已经有 `MOSAEL_SECRET_KEY` 或明文密钥时不碰钥匙串；没有封存密钥时照旧让后端生成。
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const expandHome = (value) => value.replace(/^~(?=$|[\\/])/, homedir());
const dataDir = process.env.MOSAEL_DATA_DIR
  ? resolve(expandHome(process.env.MOSAEL_DATA_DIR))
  : join(homedir(), ".mosael");
const env = {
  ...process.env,
  MOSAEL_LOCAL_DESKTOP: process.env.MOSAEL_LOCAL_DESKTOP || "1",
};

if (!env.MOSAEL_SECRET_KEY && !existsSync(join(dataDir, "secret.key")) && existsSync(join(dataDir, "secret.key.sealed"))) {
  const electron = createRequire(import.meta.url)("electron");
  const key = await new Promise((resolve) => {
    const child = spawn(electron, ["--no-sandbox", join(root, "scripts", "print-master-key.cjs")], {
      env: { ...process.env, MOSAEL_DATA_DIR: dataDir },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGKILL");
    }, 30_000);
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", (error) => {
      clearTimeout(timer);
      stderr += error.message;
      resolve({ key: "", stderr });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({
        key: code === 0 ? stdout.trim() : "",
        stderr: timedOut ? `${stderr}\n钥匙串提示 30 秒内没有完成，请允许 Electron 访问后重试。` : stderr,
      });
    });
  });
  if (!key.key) {
    console.error(
      `[dev:backend] 解不开 ${join(dataDir, "secret.key.sealed")}；先启动一次桌面版并允许钥匙串访问，` +
        "或显式设置 MOSAEL_SECRET_KEY。",
    );
    if (key.stderr.trim()) console.error(key.stderr.trim());
    process.exit(1);
  }
  // 只给这个后端进程；父 shell 和别的进程看不到。
  env.MOSAEL_SECRET_KEY = key.key;
}

const child = spawn("uv", [
  "run", "--frozen", "python", "-m", "uvicorn", "app.main:app",
  "--host", "127.0.0.1",
  "--port", env.MOSAEL_BACKEND_PORT || "8800",
  "--timeout-graceful-shutdown", "5",
  "--reload",
], { cwd: join(root, "backend"), env, stdio: "inherit" });

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}
child.on("error", (error) => {
  console.error(`[dev:backend] ${error.message}`);
  process.exit(1);
});
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});
