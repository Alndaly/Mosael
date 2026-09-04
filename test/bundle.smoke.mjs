/** Launch the unpacked Electron artifact against a deliberately old database.
 *
 * A successful installer build proves only that files were copied. This smoke crosses the real
 * packaged seams: Electron locates the frozen backend, the backend upgrades an existing SQLite
 * database, health becomes ready, and the packaged renderer loads. */
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { basename, join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");

function walk(directory) {
  if (!existsSync(directory)) return [];
  const out = [];
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) out.push(...walk(path));
    else out.push(path);
  }
  return out;
}

function packagedExecutable() {
  const explicit = process.argv[2];
  if (explicit) return resolve(explicit);
  const files = walk(join(root, "release"));
  if (process.platform === "darwin") {
    return files.find((path) => path.endsWith("Mosael.app/Contents/MacOS/Mosael"));
  }
  if (process.platform === "win32") {
    return files.find((path) => /win-unpacked[\\/]Mosael\.exe$/.test(path));
  }
  return files.find((path) => basename(path) === "mosael");
}

async function freePort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolvePort(address.port));
    });
  });
}

const executable = packagedExecutable();
if (!executable) throw new Error("packaged Electron executable not found under release/");

const scratch = mkdtempSync(join(tmpdir(), "mosael-bundle-smoke-"));
const dataDir = join(scratch, "data");
const resultPath = join(scratch, "result.json");
const python = process.platform === "win32" ? "python" : "python3";
const fixture = join(root, "test", "upgrade_db_fixture.py");

try {
  const seeded = spawnSync(python, [fixture, "seed", dataDir], { stdio: "inherit" });
  if (seeded.status !== 0) throw new Error("failed to seed upgrade database");

  const child = spawn(executable, [], {
    env: {
      ...process.env,
      MOSAEL_DATA_DIR: dataDir,
      MOSAEL_BACKEND_PORT: String(await freePort()),
      MOSAEL_SMOKE_TEST_RESULT: resultPath,
    },
    stdio: "inherit",
  });
  // 超时本身说明不了任何事:这一步平时 6-7 秒,一旦跑不完 90 秒,「卡在哪」才是要的答案。
  // 主进程沿途把阶段写进 result.json,这里在清理临时目录**之前**把它和两份日志一起读出来。
  const tail = (file, lines) => {
    try {
      if (!existsSync(file)) return `${basename(file)}=<absent>`;
      return `${basename(file)} tail:\n${readFileSync(file, "utf8").trimEnd().split("\n").slice(-lines).join("\n")}`;
    } catch (error) {
      return `${basename(file)}=<unreadable: ${error.message}>`;
    }
  };
  const evidence = () => {
    const logs = join(scratch, "electron-user-data", "logs");
    return [
      existsSync(resultPath)
        ? `result.json=${readFileSync(resultPath, "utf8").replace(/\s+/g, " ")}`
        : "result.json=<never written — 主进程没走到任何一站>",
      tail(join(logs, "main.log"), 25),
      tail(join(logs, "backend.log"), 15),
    ].join("\n");
  };

  const exitCode = await new Promise((resolveExit, reject) => {
    const timeout = setTimeout(() => {
      const seen = evidence();
      child.kill();
      reject(new Error(`packaged Electron smoke timed out after 90s\n${seen}`));
    }, 90_000);
    child.once("error", reject);
    child.once("exit", (code) => {
      clearTimeout(timeout);
      resolveExit(code);
    });
  });
  if (exitCode !== 0) throw new Error(`packaged Electron exited with ${exitCode}\n${evidence()}`);
  if (!existsSync(resultPath)) throw new Error("packaged Electron did not write a smoke result");
  const result = JSON.parse(readFileSync(resultPath, "utf8"));
  if (!result.packaged || !result.backendHealthy || !result.rendererLoaded || !result.desktopBridgeReady) {
    throw new Error(`incomplete packaged startup: ${JSON.stringify(result)}`);
  }

  const verified = spawnSync(python, [fixture, "verify", dataDir], { stdio: "inherit" });
  if (verified.status !== 0) throw new Error("database upgrade verification failed");
  console.log(`bundle smoke passed (${process.platform}, app ${result.version})`);
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
