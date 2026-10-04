#!/usr/bin/env node
/**
 * 开发时拉起 Electron 的那一层(frontend 的 electron:dev:`node ../electron/dev-loop.cjs ../electron/main.cjs`)。
 *
 * 为什么要这一层:`pnpm dev` 用 `concurrently -k` 跑 vite、后端、几个 watch 和 Electron,**任何一栏退出整组都会被
 * 杀**。主进程的代码改了(watch 重编了 bundle)要重启 Electron 才生效,而 `app.relaunch()` + 退出会先让 Electron
 * 这一栏退出 —— vite、后端跟着被带走。所以由这一层守着:主进程以「要重启」的退出码(RESTART_EXIT_CODE)退出时
 * 再拉一遍,这一栏不退,别的栏照常;别的退出(关掉应用、崩了、被信号杀了)照原样退,concurrently 照旧收工。
 *
 * 拉起时带上 MOSAEL_DEV_RESTART_CODE:主进程据此知道可以要求重启(见 main.cjs 的 restartMain),没有它就只提示
 * 「重启 Mosael 后生效」、不给按钮。
 */
const { spawn: spawnProcess } = require("node:child_process");

/** 「要重启」的退出码。75 = EX_TEMPFAIL:临时性的、再来一次就好。 */
const RESTART_EXIT_CODE = 75;

/**
 * @param {{
 *   spawn: (env: Record<string, string>) => import("node:events").EventEmitter & { kill(signal?: string): void },
 *   onExit: (code: number) => void,
 *   log?: (line: string) => void,
 *   signals?: import("node:events").EventEmitter,
 * }} opts
 */
function superviseElectron({ spawn, onExit, log = (line) => console.log(line), signals = process }) {
  /** @type {(import("node:events").EventEmitter & { kill(signal?: string): void }) | null} */
  let child = null;
  const start = () => {
    child = spawn({ MOSAEL_DEV_RESTART_CODE: String(RESTART_EXIT_CODE) });
    child.once("exit", (/** @type {number | null} */ code, /** @type {string | null} */ signal) => {
      if (code === RESTART_EXIT_CODE) {
        log("[dev-loop] main process asked for a restart: relaunching Electron (vite and backend keep running)");
        start();
        return;
      }
      child = null;
      onExit(code ?? (signal ? 1 : 0));
    });
  };
  for (const name of ["SIGINT", "SIGTERM"]) {
    signals.on(name, () => {
      child?.kill(name);
    });
  }
  start();
}

if (require.main === module) {
  // 在 node 里 require("electron") 拿到的是 Electron 可执行文件的路径。
  const electronBinary = /** @type {string} */ (/** @type {unknown} */ (require("electron")));
  superviseElectron({
    spawn: (env) => spawnProcess(electronBinary, process.argv.slice(2), { stdio: "inherit", env: { ...process.env, ...env } }),
    onExit: (code) => process.exit(code),
  });
}

module.exports = { superviseElectron, RESTART_EXIT_CODE };
