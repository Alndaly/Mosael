// 浏览器自动化 worker:与发布 worker 并列的第二个拉取循环。轮询 /api/browser/worker/claim 认领
// 动作,用 PageDriver 在会话隔离视图上执行,回报结果;并把「最近操作的会话」定时截帧推给前端做
// 实时预览(这些自动化视图是离屏的,用户否则看不到)。

import type { LiveViewFrame } from "./types";
import { BrowserSessionManager } from "./browserSessions";
import { executeBrowserAction } from "./browserActions";
import { browserBackend, type ClaimedAction } from "./browserBackend";
import { plog } from "./log";

const IDLE_MS = 1200;
const BUSY_MS = 150;
const PREVIEW_MS = 500; // 预览截帧节奏(~2fps)
const PREVIEW_WINDOW_MS = 15_000; // 最近一次动作后持续预览的时长,之后停帧省资源
const delay = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

let manager: BrowserSessionManager | null = null;
let generation = 0; // 递增即令旧 loop/预览自然退出
let onFrame: ((frame: LiveViewFrame) => void) | null = null;
let activeSessionId: string | null = null; // 预览跟随最近操作的会话
let lastActionAt = 0;
let previewTimer: ReturnType<typeof setInterval> | null = null;
let capturing = false;

export function startBrowserWorker(opts: { onFrame?: (frame: LiveViewFrame) => void } = {}): void {
  stopBrowserWorker();
  manager = new BrowserSessionManager();
  onFrame = opts.onFrame ?? null;
  const gen = ++generation;
  plog("browser worker started, generation", gen);
  void loop(gen);
  previewTimer = setInterval(() => void capturePreview(gen), PREVIEW_MS);
}

export function stopBrowserWorker(): void {
  generation++;
  if (previewTimer) {
    clearInterval(previewTimer);
    previewTimer = null;
  }
  manager?.destroyAll();
  manager = null;
  onFrame = null;
  activeSessionId = null;
}

async function capturePreview(gen: number): Promise<void> {
  if (gen !== generation || !manager || !onFrame || capturing) return;
  if (!activeSessionId || Date.now() - lastActionAt > PREVIEW_WINDOW_MS) return;
  const driver = manager.getDriver(activeSessionId);
  if (!driver) return;
  capturing = true;
  try {
    const dataUrl = await driver.captureBase64();
    if (dataUrl && onFrame && gen === generation) onFrame({ sessionId: activeSessionId, dataUrl });
  } catch {
    /* 截帧失败忽略,下一拍再来 */
  } finally {
    capturing = false;
  }
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
  activeSessionId = action.session_id; // 预览切到当前操作的会话
  lastActionAt = Date.now();
  try {
    if (action.action === "close") {
      mgr.destroy(action.session_id);
      if (activeSessionId === action.session_id) activeSessionId = null;
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
