// 浏览器自动化 worker:与发布 worker 并列的第二个拉取循环。轮询 /api/browser/worker/claim 认领
// 动作,用 PageDriver 在会话隔离视图上执行,回报结果。绝不与发布任务同流(独立端点 + 独立分区)。
import type { BaseWindow } from "electron";

import { BrowserSessionManager } from "./browserSessions";
import { executeBrowserAction } from "./browserActions";
import { browserBackend, type ClaimedAction } from "./browserBackend";
import { plog } from "./log";

const IDLE_MS = 1200;
const BUSY_MS = 150;
const delay = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

let manager: BrowserSessionManager | null = null;
let generation = 0; // 递增即令旧 loop 自然退出(stop 或重启)

export function startBrowserWorker(opts: { window: BaseWindow }): void {
  stopBrowserWorker();
  manager = new BrowserSessionManager(opts.window);
  const gen = ++generation;
  plog("browser worker started, generation", gen);
  void loop(gen);
}

export function stopBrowserWorker(): void {
  generation++;
  manager?.destroyAll();
  manager = null;
}

async function loop(gen: number): Promise<void> {
  while (gen === generation) {
    let didWork = false;
    try {
      await browserBackend.heartbeat();
      const action = await browserBackend.claim();
      if (action && gen === generation) {
        didWork = true;
        await handleAction(action);
      }
    } catch (error) {
      plog("browser worker loop error:", error instanceof Error ? error.message : String(error));
    }
    await delay(didWork ? BUSY_MS : IDLE_MS);
  }
}

async function handleAction(action: ClaimedAction): Promise<void> {
  const mgr = manager;
  if (!mgr) return;
  try {
    if (action.action === "close") {
      mgr.destroy(action.session_id);
      await browserBackend.report(action.id, { status: "done", result: {} });
      return;
    }
    const driver = mgr.ensure(action.session_id, action.partition);
    const outcome = await executeBrowserAction(driver, action.action, action.args);
    await browserBackend.report(action.id, {
      status: "done",
      result: outcome.value !== undefined ? { value: outcome.value } : {},
      last_url: outcome.lastUrl,
    });
    plog("browser action done:", action.action, action.session_id);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    plog("browser action failed:", action.action, message);
    await browserBackend.report(action.id, { status: "failed", error: message }).catch(() => undefined);
  }
}
