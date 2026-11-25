// macOS 灵动岛原生浮层:一个独立的 NSPanel 进程,不属于 Mosael 的主窗口。
//
// 它只认识两类消息:
// - 主进程 → helper:每行一份 JSON 快照 `{ activities: [...] }`(状态、标题、进度);
// - helper → 主进程:用户点了岛上的某一件 `{ type: "open", id }`。
//
// 为什么不是 Widget Extension / ActivityKit:macOS 原生 Live Activities 要到 27.3 Beta;
// 当前支持的系统的「灵动岛」都是 AppKit NSPanel 浮层(NotchNook / Boring Notch 同一路线)。
// 这条进程边界让未来接入 ActivityKit 时不需要动渲染层和任务中心。
const fs = require("node:fs");
const { spawn: defaultSpawn } = require("node:child_process");

/** 渲染层传下来的 Activity 里带着 React 图标与点击函数;这里只保留原生认识的字段。 */
function toWire(activity) {
  if (!activity || typeof activity !== "object") return null;
  const id = typeof activity.id === "string" ? activity.id : "";
  const state = activity.state === "done" || activity.state === "failed" ? activity.state : "ongoing";
  const title = typeof activity.title === "string" ? activity.title : "";
  if (!id || !title) return null;
  const detail = typeof activity.detail === "string" && activity.detail ? activity.detail : undefined;
  const progress = typeof activity.progress === "number" && Number.isFinite(activity.progress)
    ? Math.min(Math.max(activity.progress, 0), 1)
    : undefined;
  const priority = Number.isInteger(activity.priority) ? activity.priority : undefined;
  return { id, state, title, ...(detail ? { detail } : {}), ...(progress === undefined ? {} : { progress }), ...(priority === undefined ? {} : { priority }) };
}

function encodeState(activities) {
  const wire = (Array.isArray(activities) ? activities : []).map(toWire).filter(Boolean).slice(0, 8);
  return `${JSON.stringify({ activities: wire })}\n`;
}

/** 一行 stdout:只认 `{type:"open",id}`;其余(日志、未来扩展)忽略。 */
function parseIslandOutput(line) {
  try {
    const value = JSON.parse(line);
    if (value && value.type === "open" && typeof value.id === "string" && value.id) {
      return { type: "open", id: value.id };
    }
  } catch {
    // 不是协议行就当作原生侧日志,不抛。
  }
  return null;
}

/**
 * @param {{
 *   binaryPath: string,
 *   onOpen?: (id: string) => void,
 *   log?: (line: string) => void,
 *   spawn?: typeof defaultSpawn,
 *   exists?: (path: string) => boolean,
 *   platform?: NodeJS.Platform,
 * }} options
 */
function createMacosIsland(options) {
  const {
    binaryPath,
    onOpen = () => {},
    log = (line) => console.warn(`[macos-island] ${line}`),
    spawn = defaultSpawn,
    exists = (path) => fs.existsSync(path),
    platform = process.platform,
  } = options;
  let child = null;
  let disposed = false;
  let lastState = encodeState([]);
  let buffer = "";

  function start() {
    if (disposed || child || platform !== "darwin" || !exists(binaryPath)) return false;
    try {
      child = spawn(binaryPath, [], { stdio: ["pipe", "pipe", "pipe"] });
    } catch (error) {
      log(`spawn failed: ${String(error).slice(0, 200)}`);
      child = null;
      return false;
    }
    child.stdout?.setEncoding?.("utf8");
    child.stderr?.setEncoding?.("utf8");
    child.stdout?.on("data", (chunk) => {
      buffer += String(chunk);
      let index;
      while ((index = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, index).trim();
        buffer = buffer.slice(index + 1);
        const event = parseIslandOutput(line);
        if (event) onOpen(event.id);
        else if (line) log(line.slice(0, 300));
      }
    });
    child.stderr?.on("data", (chunk) => log(String(chunk).trim().slice(0, 300)));
    child.on("error", (error) => log(`process error: ${String(error).slice(0, 200)}`));
    child.on("exit", (code, signal) => {
      if (!disposed) log(`exited: code=${code ?? "null"} signal=${signal ?? "null"}`);
      child = null;
    });
    write(lastState);
    return true;
  }

  function write(line) {
    if (!child || !child.stdin || child.stdin.destroyed) return;
    try {
      child.stdin.write(line);
    } catch (error) {
      log(`write failed: ${String(error).slice(0, 200)}`);
    }
  }

  function setActivities(activities) {
    lastState = encodeState(activities);
    if (!child) start();
    else write(lastState);
  }

  function dispose() {
    disposed = true;
    if (child) {
      try {
        child.stdin?.end();
        child.kill("SIGTERM");
      } catch {
        // 退出路径上尽力而为。
      }
      child = null;
    }
  }

  return { start, setActivities, dispose, get running() { return Boolean(child); } };
}

module.exports = { createMacosIsland, encodeState, parseIslandOutput, toWire };
