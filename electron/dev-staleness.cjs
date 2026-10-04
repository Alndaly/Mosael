/**
 * 开发时主进程过期了没有:主进程启动时加载的产物(electron/ 下的 .cjs —— main.cjs、publish / system / preload
 * 这几个 bundle,watch 会重编它们;以及 main 直接 require 的那几个模块)后来变了,而正在跑的主进程还是启动时
 * 那一版。渲染层由 vite 热更新,主进程不会 —— 渲染层的新代码去调旧主进程里没有的处理器,就是用户撞上的那条
 * 「No handler registered」。
 *
 * **按内容判,不按「文件被写过」判**:watch 一启动会把没变的 bundle 原样再写一遍,那不算过期;改了又改回原样的
 * 也不算。只看 electron/ 这一层(publish/*.ts 这些源码编进 bundle 才会被加载,看 bundle 就够)。
 *
 * 只在开发时用(main.cjs 里 `!app.isPackaged` 才起),正式打包的应用不受影响。
 */
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

/** 主进程加载的是这一层的 .cjs;拉起 Electron 的那个脚本(dev-loop.cjs)自己改了要重跑 pnpm dev,不在此列。 */
const isRuntimeFile = (/** @type {string} */ name) => name.endsWith(".cjs") && name !== "dev-loop.cjs";

/** @param {string} file */
function hashOf(file) {
  try {
    return crypto.createHash("sha1").update(fs.readFileSync(file)).digest("hex");
  } catch {
    return null; // 被删了 / 正写到一半
  }
}

/**
 * @param {{
 *   dir: string,
 *   onChange: (files: string[]) => void,
 *   debounceMs?: number,
 *   watch?: (dir: string, listener: (event: string, name: string | null) => void) => { close(): void },
 * }} opts
 */
function createStalenessWatcher({ dir, onChange, debounceMs = 400, watch = (target, listener) => fs.watch(target, listener) }) {
  /** @type {Map<string, string | null>} */
  const baseline = new Map();
  for (const name of fs.readdirSync(dir)) if (isRuntimeFile(name)) baseline.set(name, hashOf(path.join(dir, name)));
  /** @type {Set<string>} */
  const stale = new Set();
  /** @type {Set<string>} */
  const pending = new Set();
  /** @type {ReturnType<typeof setTimeout> | null} */
  let timer = null;
  const settle = () => {
    timer = null;
    let changed = false;
    for (const name of pending) {
      const now = hashOf(path.join(dir, name));
      const was = baseline.has(name) ? baseline.get(name) : undefined;
      const isStale = was === undefined ? now !== null : now !== was;
      if (isStale && !stale.has(name)) {
        stale.add(name);
        changed = true;
      } else if (!isStale && stale.delete(name)) {
        changed = true;
      }
    }
    pending.clear();
    if (changed) onChange([...stale].sort());
  };
  const watcher = watch(dir, (_event, name) => {
    if (!name || !isRuntimeFile(name)) return;
    pending.add(name);
    if (timer) clearTimeout(timer);
    timer = setTimeout(settle, debounceMs);
  });
  return {
    stale: () => [...stale].sort(),
    close() {
      if (timer) clearTimeout(timer);
      watcher.close();
    },
  };
}

module.exports = { createStalenessWatcher };
