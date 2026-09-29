"use strict";

/**
 * 壳这一侧的后端生命周期规则(和 backend app/core/lifeline.py 配对)。
 *
 * - **端口上那个后端能不能复用**:此前只看 /api/health 回不回 `ok`。上次壳被强杀留下的孤儿后端、
 *   另一个版本、指着另一个数据目录的后端,都会被当成"自己的"接着用 —— 界面连上的是一份别的数据。
 *   现在健康检查带着版本和数据目录指纹,打包版两样都对得上才复用。开发时照旧宽松:手动起的 uvicorn
 *   版本号是 package.json 里那个,数据目录也常常是故意指过去的。
 * - **意外退出就退避重启**:此前后端一崩,弹一个「请重启 Mosael」就完了,整个应用只剩个空壳。
 *   现在按 1s、2s、4s 退避重拉,五分钟里连崩三次才认输、弹框。
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
  };
}

module.exports = { createRestartPolicy, dataDirId, reusable };
