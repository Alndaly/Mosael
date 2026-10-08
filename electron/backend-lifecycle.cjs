"use strict";

/**
 * 壳这一侧的后端生命周期规则(和 backend app/core/lifeline.py 配对)。
 *
 * - **端口上那个后端能不能复用**:此前只看 /api/health 回不回 `ok`。上次壳被强杀留下的孤儿后端、
 *   另一个版本、指着另一个数据目录的后端,都会被当成"自己的"接着用 —— 界面连上的是一份别的数据。
 *   现在健康检查带着版本和数据目录指纹,打包版两样都对得上才复用。开发时照旧宽松:手动起的 uvicorn
 *   版本号是 package.json 里那个,数据目录也常常是故意指过去的。
 * - **意外退出就退避重启**:此前后端一崩,弹一个「请重启 Mosael」就完了,整个应用只剩个空壳。
 *   现在按 1s、2s、4s 退避重拉,五分钟里连崩三次才认输;认输之后人点「再试一次」还能重来(`retry`)。
 * - **只要它还活着就等它就绪**:冷启动(首次打开时系统扫描整个安装包)、升级后的数据迁移可能要好几分钟。此前固定等
 *   30 秒,过了就弹「启动失败」并退出 —— 退出时 SIGTERM 又把正在迁移的后端打断,下次照样超时。现在只有进程退出才算没起来,
 *   等的时候由调用方显示进度(`onWaiting`)。
 * - **打包版不接管上一个壳的孤儿**:端口上同版本、同数据的后端只可能是上一个壳崩了 / 被强退留下的,它的 lifeline 一看
 *   旧壳不在就会自己退 —— 接管它,几秒之后就没了后端、也没人重启。所以等它退了再自己拉起。
 * - **Windows 上退出时请后端自己收尾**:Node 的 kill 在 Windows 上就是强杀,后端的收尾(停本机服务、调度线程)不跑,
 *   它起的子进程成了孤儿;而壳一退,libuv 给子进程挂的作业对象还会把后端一并强杀。所以先请它收尾、等它退,再让壳退。
 *
 * `createBackendSupervisor` 只管顺序和规则:怎么拼命令、弹什么框都由 main.cjs 注入,于是能单独测(backend-lifecycle.test.ts)。
 */

const crypto = require("node:crypto");

/** 与后端 lifeline.data_dir_id 同一个算法:原样字符串的 sha256 前 16 位。 */
function dataDirId(dataDir) {
  return crypto.createHash("sha256").update(String(dataDir), "utf8").digest("hex").slice(0, 16);
}

/**
 * @param {Record<string, unknown> | null} health  /api/health 的回应体
 * @param {{ version: string, dataDir: string, strict: boolean }} expected
 * @returns {{ ok: boolean, reason?: string }}
 */
function reusable(health, expected) {
  if (!health || health.status !== "ok") return { ok: false, reason: "unhealthy" };
  if (!expected.strict) return { ok: true };
  if (health.app !== "mosael") return { ok: false, reason: "not a Mosael backend" };
  if (health.version !== expected.version) {
    return { ok: false, reason: `version ${String(health.version)} != ${expected.version}` };
  }
  if (health.data_dir_id !== dataDirId(expected.dataDir)) return { ok: false, reason: "different data directory" };
  return { ok: true };
}

/**
 * 崩溃重启的退避:`next(now)` 回这次该等多少毫秒,回 null 表示近期崩得太多、该认输了。
 * @param {{ maxRestarts?: number, windowMs?: number, baseDelayMs?: number }} [options]
 */
function createRestartPolicy({ maxRestarts = 3, windowMs = 5 * 60_000, baseDelayMs = 1000 } = {}) {
  const recent = [];
  return {
    next(now = Date.now()) {
      while (recent.length && now - recent[0] > windowMs) recent.shift();
      if (recent.length >= maxRestarts) return null;
      const delay = baseDelayMs * 2 ** recent.length;
      recent.push(now);
      return delay;
    },
    /** 人明确要「再试一次」:之前的几次不再算数。 */
    reset() {
      recent.length = 0;
    },
  };
}

/** 进程退出了没有(正常退出有 exitCode,被信号杀掉有 signalCode)。 */
const exited = (proc) => proc.exitCode !== null || Boolean(proc.signalCode);

/**
 * @typedef {import("node:events").EventEmitter & {
 *   exitCode: number | null, signalCode?: string | null, kill(signal?: string): boolean
 * }} BackendProcess
 * @typedef {{ status: "ready" | "reused" | "portTaken" | "exited" | "cancelled" | "timeout", reason?: string, code?: string | number | null }} StartResult
 */

/**
 * @param {{
 *   probe: () => Promise<Record<string, unknown> | null>,
 *   spawn: () => Promise<BackendProcess | null>,
 *   expected: { version: string, dataDir: string, strict: boolean },
 *   platform?: string,
 *   requestShutdown?: () => Promise<boolean>,
 *   onGiveUp?: (lastExit: string | number | null) => void,
 *   log?: (kind: string, detail: string) => void,
 *   pollMs?: number, orphanGraceMs?: number, shutdownGraceMs?: number,
 *   sleep?: (ms: number) => Promise<void>,
 *   now?: () => number,
 *   schedule?: (callback: () => void, ms: number) => unknown,
 *   policy?: ReturnType<typeof createRestartPolicy>,
 * }} options
 */
function createBackendSupervisor({
  probe,
  spawn,
  expected,
  platform = process.platform,
  requestShutdown = async () => false,
  onGiveUp = () => undefined,
  log = () => undefined,
  pollMs = 300,
  orphanGraceMs = 20_000,
  shutdownGraceMs = 12_000,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  now = () => Date.now(),
  schedule = (callback, ms) => setTimeout(callback, ms),
  policy = createRestartPolicy(),
}) {
  /** @type {BackendProcess | null} 我们拉起的、还活着的那个 */
  let child = null;
  /** 退出、恢复备份:之后的退出不算意外,也不再重启。 */
  let stopping = false;
  let restartPending = false;
  let gaveUp = false;
  /** 我们拉起的进程里,哪些是「第一次启动」的那个、哪些就绪过(第一次启动没起来由 start 自己报,不当作崩溃)。 */
  const initial = new WeakSet();
  const readyOnce = new WeakSet();
  /** 已经发过 SIGTERM 的。 */
  const terminated = new WeakSet();

  /** 只要进程还活着就等;`deadlineMs` 只给冒烟用(没人看着,得有个头)。 */
  async function waitReady(proc, { onWaiting, deadlineMs } = {}) {
    const started = now();
    for (;;) {
      if (exited(proc)) return "exited";
      const body = await probe();
      if (body && body.status === "ok" && !exited(proc)) return "ready";
      if (deadlineMs && now() - started >= deadlineMs) return "timeout";
      onWaiting?.(now() - started);
      await sleep(pollMs);
    }
  }

  /** 端口上已经有一个健康的后端。回 null = 它已经退了,接着自己拉起。 */
  async function settleExisting(existing) {
    const verdict = reusable(existing, expected);
    if (!verdict.ok) return { status: "portTaken", reason: verdict.reason };
    // 开发:手动起的 uvicorn(pnpm dev 那一栏),本来就该用它。
    if (!expected.strict) return { status: "reused" };
    log("backend-orphan", "a backend of this version and data folder is still on the port; waiting for it to exit");
    const deadline = now() + orphanGraceMs;
    while (now() < deadline) {
      await sleep(pollMs);
      if (!(await probe())) return null;
    }
    return { status: "portTaken", reason: "a previous Mosael backend on this port did not shut down" };
  }

  function onExit(proc, code, signal) {
    if (child === proc) child = null;
    if (stopping) return;
    log("backend-exit", `code=${code} signal=${signal}`);
    // 第一次启动、还没就绪就退了:start() 会报「没起来」,不在这里重拉。
    if (initial.has(proc) && !readyOnce.has(proc)) return;
    scheduleRestart(code ?? signal);
  }

  function scheduleRestart(lastExit) {
    const delay = policy.next(now());
    if (delay === null) {
      gaveUp = true;
      onGiveUp(lastExit);
      return;
    }
    restartPending = true;
    schedule(() => {
      restartPending = false;
      if (stopping || child) return;
      void start().then((result) => {
        log("backend-restarted", result.status);
        if (result.status === "portTaken") {
          gaveUp = true;
          onGiveUp(result.reason ?? null);
        }
      });
    }, delay);
  }

  /**
   * 起一个(端口上已有能用的就用它)并等它就绪。
   * @param {{ initial?: boolean, onWaiting?: (elapsedMs: number) => void, deadlineMs?: number }} [options]
   * @returns {Promise<StartResult>}
   */
  async function start({ initial: isInitial = false, onWaiting, deadlineMs } = {}) {
    const existing = await probe();
    if (existing) {
      const settled = await settleExisting(existing);
      if (settled) return settled;
    }
    const proc = await spawn();
    if (!proc) return { status: "cancelled" };
    if (isInitial) initial.add(proc);
    child = proc;
    proc.once("exit", (code, signal) => onExit(proc, code, signal));
    const outcome = await waitReady(proc, { onWaiting, deadlineMs });
    if (outcome === "ready") {
      readyOnce.add(proc);
      return { status: "ready" };
    }
    if (outcome === "timeout") return { status: "timeout" };
    return { status: "exited", code: proc.exitCode ?? proc.signalCode ?? null };
  }

  /** 连崩认输之后人要「再试一次」。正跑着、正要重拉时什么都不做。 */
  async function retry() {
    if (stopping) return { status: "cancelled" };
    if (child || restartPending) return { status: "running" };
    gaveUp = false;
    policy.reset();
    const result = await start();
    if (result.status !== "ready" && result.status !== "reused" && !child && !restartPending) gaveUp = true;
    return result;
  }

  function waitExit(proc, ms) {
    if (exited(proc)) return Promise.resolve(true);
    return new Promise((resolve) => {
      const timer = setTimeout(() => resolve(false), ms);
      proc.once("exit", () => {
        clearTimeout(timer);
        resolve(true);
      });
    });
  }

  /**
   * 应用退出时收尾。POSIX:SIGTERM 就是「请你收尾」,不等(它在后台收完自己退)。Windows:kill 就是强杀,所以先请它
   * 自己收尾、等它退,等不到再强杀。
   */
  async function shutdown() {
    stopping = true;
    const proc = child;
    if (!proc || exited(proc)) return;
    if (platform !== "win32") {
      terminated.add(proc);
      proc.kill("SIGTERM");
      return;
    }
    const asked = await requestShutdown().catch(() => false);
    if (asked && (await waitExit(proc, shutdownGraceMs))) return;
    log("backend-shutdown", asked ? "did not exit in time; terminating" : "could not ask it to shut down; terminating");
    proc.kill();
  }

  /** 进程正要退出(app.exit、process 的 exit 事件):来不及等,能发的就发。已经请它退过的不再发 —— uvicorn 收到第二个 SIGTERM 就不等收尾了。 */
  function killNow() {
    stopping = true;
    if (child && !exited(child) && !terminated.has(child)) child.kill("SIGTERM");
  }

  /** 恢复备份要先停掉后端(要的是我们拉起的那个:换数据目录时它不能还开着库)。 */
  async function stopForRestore({ forceAfterMs = 8_000, giveUpAfterMs = 15_000 } = {}) {
    const proc = child;
    if (!proc || exited(proc)) return false;
    stopping = true;
    const done = waitExit(proc, giveUpAfterMs);
    proc.kill("SIGTERM");
    const force = setTimeout(() => proc.kill("SIGKILL"), forceAfterMs);
    const stopped = await done;
    clearTimeout(force);
    if (!stopped) throw new Error("backend did not stop");
    return true;
  }

  /** 恢复没成:接着用原来的数据,把后端拉回来。 */
  function resumeAfterFailedRestore() {
    stopping = false;
    return start();
  }

  return {
    start,
    retry,
    shutdown,
    killNow,
    stopForRestore,
    resumeAfterFailedRestore,
    /** Windows 上退出前要等它收尾(见 shutdown)。 */
    needsGracefulShutdown: () => platform === "win32" && Boolean(child) && !exited(child),
    get running() {
      return Boolean(child) && !exited(child);
    },
    get gaveUp() {
      return gaveUp;
    },
  };
}

module.exports = { createBackendSupervisor, createRestartPolicy, dataDirId, reusable };
