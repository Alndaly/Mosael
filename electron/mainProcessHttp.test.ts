import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname);

/** electron/ 下主进程的源码(不含打包产物和测试)。 */
function sources(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sources(full);
    if (!/\.(c|m)?[jt]s$/.test(entry.name)) return [];
    if (/\.bundle\.cjs$|\.test\.ts$|\.d\.c?ts$/.test(entry.name)) return [];
    return [full];
  });
}

describe("主进程的 HTTP 请求", () => {
  /**
   * 主进程发请求一律走 Electron 的 `net.fetch`(Chromium 的网络栈),不用 Node 的全局 `fetch`(undici)。
   *
   * Electron 44 带的 undici 在写请求头时调 `socket.setTypeOfService`,这一步在 macOS 上对一条已经被对端
   * 重置的连接会**同步**抛 `EINVAL`,而且没被 undici 自己接住 —— 它成了主进程的未捕获异常,弹出
   * 「主进程发生 JavaScript 错误」。触发它的正是最常见的一幕:开发时后端重载、或本机后端挂了,
   * 健康检查和发布执行器的轮询撞上断掉的 keep-alive 连接。
   */
  it("不用 Node 的全局 fetch", () => {
    const offenders = sources(ROOT).flatMap((file) =>
      fs
        .readFileSync(file, "utf8")
        .split("\n")
        .map((line, index) => ({ line, index }))
        .filter(({ line }) => /(^|[^.\w])fetch\(/.test(line) && !/^\s*(\/\/|\*)/.test(line))
        .map(({ index }) => `${path.relative(ROOT, file)}:${index + 1}`),
    );
    expect(offenders).toEqual([]);
  });
});
