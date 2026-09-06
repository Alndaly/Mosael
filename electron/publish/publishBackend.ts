// 发布执行器 ↔ Mosael 后端(/api/publish)的薄客户端。后端是任务的单一事实源:执行器
// 认领待办、回报状态、更新账号登录态,都走这里。本地默认 owner,后端 publish 权限门放行本地。
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import { plog } from "./log";

const BASE =
  process.env.MOSAEL_BACKEND_URL || `http://127.0.0.1:${process.env.MOSAEL_BACKEND_PORT || 8800}`;

interface BackendTask {
  id: string;
  account_id: string;
  account_name: string;
  platform: string;
  proxy: string | null;
  video_path: string;
  title: string;
  tags: string[];
  description: string;
  short_title: string;
  /** 平台自己的发布选项(可见性等)。后端建任务时已补全默认值,这里拿到的一定是完整字典。 */
  options?: Record<string, unknown>;
  status: string;
}

// 共享密钥:后端每次启动写入数据目录(0600),worker 读取后随每个请求发送。这条通道没有用户
// 会话,而"后端只听 127.0.0.1"挡不住浏览器 —— 用户随便打开一个网页就能 POST 到本机。真正把
// worker 和网页区分开的,是 worker 读得到本地文件。后端重启会换密钥,所以每次都重读:缓存下来
// 会在重启后静默失效,而失败是 401 不是超时,很难查。
function readWorkerKey(): string {
// 配了 MOSAEL_WORKER_KEY 就用它:后端在**另一台机器**上时,本地这份文件要么过期要么不存在
// (密钥写在后端自己的数据目录里)。两边配同一个值,这条通道就跨得过网络 —— 见后端
// core/worker_key 里那段"为什么不是用用户会话换令牌"。
  const configured = (process.env.MOSAEL_WORKER_KEY || "").trim();
  if (configured) return configured;
  const dir =
    process.env.MOSAEL_DATA_DIR ||
    join(homedir(), ".mosael");
  try {
    return readFileSync(join(dir, "publish-worker.key"), "utf8").trim();
  } catch {
    plog("worker key unreadable — the backend may not have started yet");
    return "";
  }
}

async function req<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-Mosael-Worker-Key": readWorkerKey() };
  if (body) headers["Content-Type"] = "application/json";
  const res = await fetch(`${BASE}/api/publish${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    // 服务器有响应但报错(4xx/5xx):必须落日志,这类错误静默过就是任务卡死的根源。
    const detail = await res.text().catch(() => "");
    plog("req failed:", method, path, res.status, detail.slice(0, 300));
    throw new Error(`${method} ${path} → ${res.status}`);
  }
  const text = await res.text();
  return (text ? JSON.parse(text) : {}) as T;
}

interface CheckAccount {
  owner: string;
  account_id: string;
  platform: string;
  name: string | null;
  proxy?: string | null;
  // 复检前的登录态:执行器据此判断「从 bound 变 login_required」才发失效通知。
  binding_status?: string | null;
}

/** 认领一条到期的待办(后端原子地把它翻成 running);无待办返回 { task: null }。
 *  excludeAccounts:执行器正在跑发布任务的账号——后端跳过它们的 pending(同账号共享一个内嵌视图,
 *  不能并发;有限并发靠「跨账号并发、同账号串行」)。 */
/**
 * 这个执行器叫什么。**跨重启稳定,每台机器一个。**
 *
 * 后端用它分辨任务归属:回收悬挂任务的判据之一是「这个账号不在我当前在跑的集合里」,而这句话
 * 只有认领者说了才算数 —— 两个执行器各自拿自己的集合去判对方的任务,结论必然是"孤儿",
 * 于是互相把对方正在跑的任务标成中断(见后端 publish/worker.reclaim_orphaned_running)。
 *
 * **必须跨重启稳定**:重启后第一拍要认出自己那些没跑完的任务并收回来,那是这条判据存在的
 * 全部理由。每次启动换一个新 id 的话,自己的孤儿就永远等超时。
 *
 * 允许用 MOSAEL_WORKER_ID 覆盖 —— 容器里数据目录常常是临时的,那时得由部署方给名字。
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
    // 还没有,下面现生成一个。
  }
  const fresh = randomUUID();
  try {
    mkdirSync(dir, { recursive: true });
    writeFileSync(file, fresh, { mode: 0o600 });
  } catch (error) {
    // 写不下就只在本进程里用:退化成"每次重启换个名字",而后果只是自己的孤儿要等超时,
    // 不会去误伤别人的任务 —— 比因为写不了文件就不干活好。
    plog("worker id not persisted:", error instanceof Error ? error.message : String(error));
  }
  return (workerId = fresh);
}

export function claimTask(excludeAccounts: string[] = []): Promise<{ task: BackendTask | null }> {
  return req("/worker/claim", "POST", { exclude_accounts: excludeAccounts, worker: readWorkerId() });
}

/** 认领一个「该复检登录态」的账号(bound/login_required 且太久没查);无则 { account: null }。 */
export function claimCheck(): Promise<{ account: CheckAccount | null }> {
  return req("/worker/claim-check", "POST");
}

/** 触发一轮全量巡检:把所有账号标记为待复检(执行器开机时调一次)。 */
export function markDue(): Promise<{ marked: number }> {
  return req("/worker/mark-due", "POST");
}

export function reportTask(
  taskId: string,
  patch: { status: string; error_message?: string | null; screenshot_path?: string | null },
): Promise<unknown> {
  // /worker/* 免鉴权、按 id 跨 owner 定位(执行器是无 token 的 Node 进程)。
  return req("/worker/report", "PATCH", { task_id: taskId, ...patch });
}

export function patchAccount(
  accountId: string,
  patch: { binding_status?: string; last_error?: string | null },
): Promise<unknown> {
  return req("/worker/account", "PATCH", { account_id: accountId, ...patch });
}

export function heartbeat(): Promise<unknown> {
  return req("/worker/heartbeat", "POST");
}

/** 打开某账号视图前拿它的代理(用户手动登录/看页/检查页面时;后台任务/复检的代理走 claim 负载)。 */
export async function accountProxy(accountId: string): Promise<string | null> {
  try {
    const { proxy } = await req<{ proxy: string | null }>(`/worker/account/${accountId}`);
    return proxy ?? null;
  } catch {
    return null; // 拿不到就直连,别挡住手动操作
  }
}

export type { BackendTask, CheckAccount };
