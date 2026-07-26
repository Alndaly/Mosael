// 浏览器自动化执行器 ↔ 后端(/api/browser)的薄客户端。与发布同一信任边界:X-Mibu-Worker-Key
// (本机 0600 文件),后端只听 127.0.0.1。后端重启换密钥,故每次重读。
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const BASE =
  process.env.MIBU_BACKEND_URL || `http://127.0.0.1:${process.env.MIBU_BACKEND_PORT || 8800}`;

function readWorkerKey(): string {
  const dir = process.env.MIBU_DATA_DIR || join(homedir(), ".mibu-cut");
  try {
    return readFileSync(join(dir, "publish-worker.key"), "utf8").trim();
  } catch {
    return "";
  }
}

async function req<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-Mibu-Worker-Key": readWorkerKey() };
  if (body) headers["Content-Type"] = "application/json";
  const res = await fetch(`${BASE}/api/browser${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${method} ${path} → ${res.status} ${detail.slice(0, 200)}`);
  }
  const text = await res.text();
  return (text ? JSON.parse(text) : {}) as T;
}

export interface ClaimedAction {
  id: string;
  session_id: string;
  partition: string;
  kind: string; // 会话类型 ephemeral | named
  action: string;
  args: Record<string, unknown>;
}

export const browserBackend = {
  claim: () =>
    req<{ action: ClaimedAction | null }>("/worker/claim", "POST", { worker: "browser" }).then((r) => r.action),
  report: (
    actionId: string,
    patch: { status: string; result?: unknown; error?: string; last_url?: string },
  ) => req("/worker/report", "PATCH", { action_id: actionId, ...patch }),
  heartbeat: () => req("/worker/heartbeat", "POST", { worker: "browser" }),
};
