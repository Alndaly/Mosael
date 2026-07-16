// 发布执行器 ↔ mibu-video 后端(/api/publish)的薄客户端。后端是任务的单一事实源:执行器
// 认领待办、回报状态、更新账号登录态,都走这里。本地默认 owner,后端 publish 权限门放行本地。
const BASE =
  process.env.MIBU_BACKEND_URL || `http://127.0.0.1:${process.env.MIBU_BACKEND_PORT || 8800}`;

interface BackendTask {
  id: string;
  account_id: string;
  account_name: string;
  platform: string;
  video_path: string;
  title: string;
  tags: string[];
  description: string;
  short_title: string;
  dry_run: boolean;
  status: string;
}

async function req<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}/api/publish${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status}`);
  const text = await res.text();
  return (text ? JSON.parse(text) : {}) as T;
}

interface CheckAccount {
  owner: string;
  account_id: string;
  platform: string;
  name: string | null;
  // 复检前的登录态:执行器据此判断「从 bound 变 login_required」才发失效通知。
  binding_status?: string | null;
}

/** 认领一条到期的待办(后端原子地把它翻成 running);无待办返回 { task: null }。
 *  excludeAccounts:执行器正在跑发布任务的账号——后端跳过它们的 pending(同账号共享一个内嵌视图,
 *  不能并发;有限并发靠「跨账号并发、同账号串行」)。 */
export function claimTask(excludeAccounts: string[] = []): Promise<{ task: BackendTask | null }> {
  return req("/worker/claim", "POST", { exclude_accounts: excludeAccounts });
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

export type { BackendTask, CheckAccount };
