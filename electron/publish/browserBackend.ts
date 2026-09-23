// 浏览器自动化执行器 ↔ 后端(/api/browser)的薄客户端。与发布同一信任边界:X-Mosael-Worker-Key
// (本机 0600 文件),后端只听 127.0.0.1。后端重启换密钥,故每次重读。
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const BASE =
  process.env.MOSAEL_BACKEND_URL || `http://127.0.0.1:${process.env.MOSAEL_BACKEND_PORT || 8800}`;

function readWorkerKey(): string {
// 配了 MOSAEL_WORKER_KEY 就用它:后端在**另一台机器**上时,本地这份文件要么过期要么不存在
// (密钥写在后端自己的数据目录里)。两边配同一个值,这条通道就跨得过网络 —— 见后端
// core/worker_key 里那段"为什么不是用用户会话换令牌"。
  const configured = (process.env.MOSAEL_WORKER_KEY || "").trim();
  if (configured) return configured;
  const dir = process.env.MOSAEL_DATA_DIR || join(homedir(), ".mosael");
  try {
    return readFileSync(join(dir, "publish-worker.key"), "utf8").trim();
  } catch {
    return "";
  }
}

async function req<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-Mosael-Worker-Key": readWorkerKey() };
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
  /** 这一次认领的凭据(ADR-0002)。回报和心跳都要原样带回。 */
  lease_token: string;
  lease_expires_at: string;
}

/**
 * 这个执行器叫什么。**跨重启稳定,每台机器一个** —— 和发布执行器同一条理由,
 * 见 `publishBackend.readWorkerId` 上那一整页。
 *
 * 这条通道此前发的是**字面量 `"browser"`**,不是身份:后端因此分辨不出"这条动作是谁领的",
 * 而 ADR-0002 的租约、回收、心跳三件事全都建立在这个判据上。同一个目录下,发布那条道为这件事
 * 写了整整一页,隔壁这条没学。
 *
 * 复用发布那份 id 文件:一台机器上这两个执行器**本来就跑在同一个进程里**,给它们两个名字
 * 只会让"这台机器上的执行器"这个概念分叉。
 */
let workerId = "";
function readWorkerId(): string {
  if (workerId) return workerId;
  const configured = (process.env.MOSAEL_WORKER_ID || "").trim();
  if (configured) return (workerId = configured.slice(0, 64));
  const dir = process.env.MOSAEL_DATA_DIR || join(homedir(), ".mosael");
  const file = join(dir, "publish-worker.id");
  try {
    const saved = readFileSync(file, "utf8").trim();
    if (saved) return (workerId = saved);
  } catch {
    // 还没有:发布执行器那边会生成并写下它。这里退化成本进程内一个名字 —— 后果只是
    // 自己的孤儿要等租约到期,不会去误伤别人正在跑的动作。
  }
  return (workerId = `browser-${Date.now().toString(36)}`);
}

/** 我手上正在跑的那些动作 → 它们的租约令牌。心跳带着它们去续约。 */
const holding = new Map<string, string>();

export const browserBackend = {
  claim: () =>
    req<{ action: ClaimedAction | null }>("/worker/claim", "POST", { worker: readWorkerId() }).then((r) => {
      if (r.action) holding.set(r.action.id, r.action.lease_token);
      return r.action;
    }),
  report: (
    actionId: string,
    patch: { status: string; result?: unknown; error?: string; last_url?: string },
  ) => {
    const lease_token = holding.get(actionId);
    if (patch.status === "done" || patch.status === "failed") holding.delete(actionId);
    return req("/worker/report", "PATCH", { action_id: actionId, lease_token, ...patch });
  },
  /**
   * 心跳**带着手上那些动作去续约**,并把没续上的还回来。
   *
   * 没续上只有三种可能:不是你领的、令牌不对、已经被判过期 —— 三种都意味着那条动作已经不归
   * 你了,再写结果只会盖掉别人正在干的那一份。调用方据此停手。
   */
  heartbeat: async (): Promise<string[]> => {
    const claims = [...holding].map(([action_id, lease_token]) => ({ action_id, lease_token }));
    const answer = await req<{ renewed?: string[] }>("/worker/heartbeat", "POST", {
      worker: readWorkerId(),
      claims,
    });
    const renewed = new Set(answer.renewed ?? []);
    const lost = claims.map((one) => one.action_id).filter((id) => !renewed.has(id));
    for (const id of lost) holding.delete(id);
    return lost;
  },
};
