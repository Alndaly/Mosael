/** 发布执行器文件日志:userData/logs/publisher.log,同时镜像到 stdout。
 *
 * 打包版 stdout 丢失、静默 catch 曾让认领链路无法定位(任务卡 running 无迹可查),
 * 所以执行器的关键路径(claim/runTask/checkLogin/report/复检)一律落盘。 */

import { app } from "electron";
import { appendFileSync, mkdirSync } from "node:fs";
import path from "node:path";

let logFile: string | null = null;

function ensureFile(): string | null {
  if (logFile) return logFile;
  try {
    const dir = path.join(app.getPath("userData"), "logs");
    mkdirSync(dir, { recursive: true });
    logFile = path.join(dir, "publisher.log");
    return logFile;
  } catch {
    return null;
  }
}

export function plog(...parts: unknown[]): void {
  const line = `[${new Date().toISOString()}] ${parts
    .map((p) => (p instanceof Error ? p.stack || p.message : typeof p === "string" ? p : JSON.stringify(p)))
    .join(" ")}`;
  console.log("[publisher]", line);
  const file = ensureFile();
  if (file) {
    try {
      appendFileSync(file, line + "\n");
    } catch {
      /* 日志写失败不影响主流程 */
    }
  }
}
