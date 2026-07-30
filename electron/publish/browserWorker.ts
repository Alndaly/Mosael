// 浏览器自动化 worker:与发布 worker 并列的第二个拉取循环。轮询 /api/browser/worker/claim 认领动作,
// 在会话隔离的内嵌视图上执行,回报结果。
//
// 会话视图与发布账号视图**共用同一套** AccountViewManager(见 accountViews 的 createSharedViews):
// 同一套内嵌视图、同一套右下角面板叠放、同一套可信输入。此前 RPA 自己起离屏(OSR)BrowserWindow 并
// 定时截帧推给前端做预览 —— 那是"看不见就只能截图"时代的产物。现在动作到来时把视图挂成面板:
// 画面是真实渲染的(不必截帧),而且视图参与合成之后**可信指针输入可用**,智能体的点击不再只有
// isTrusted=false 那一条路。分区照旧严格隔离:ephemeral-*(内存态)/ persist:rpa-* 与发布的
// persist:openstudio-* 互不相干。
import { sharedViews } from "./accountViews";
import { executeBrowserAction } from "./browserActions";
import { browserBackend, type ClaimedAction } from "./browserBackend";
import { plog } from "./log";

const IDLE_MS = 1200;
/**
 * 会话面板的空闲自动关闭时长。智能体用完浏览器往往**不发 close 动作**就去干别的了,面板就会一直
 * 占着;每个动作 touch 一次,超过这个时长没动作就自动撤。发布任务不设这个(它在 finally 里显式撤)——
 * 因为发布会在 waitResult 里合理地静默十几分钟,按空闲扫会把还在跑的任务收掉。
 */
const PANEL_IDLE_MS = 90_000;
const BUSY_MS = 150;
const delay = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

let generation = 0; // 递增即令旧 loop 自然退出
// 本 worker 挂过面板的会话,停机时要撤干净(视图本身归共享管理器,不在这里销毁)。
const panelled = new Set<string>();

export function startBrowserWorker(): void {
  stopBrowserWorker();
  const gen = ++generation;
  plog("browser worker started, generation", gen);
  void loop(gen);
}

export function stopBrowserWorker(): void {
  generation++;
  const views = sharedViews();
  for (const sessionId of panelled) views?.panelDetach(sessionId);
  panelled.clear();
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
  const views = sharedViews();
  if (!views) {
    // 共享视图管理器由发布执行器创建(startPublishWorker)。它没起来说明宿主窗口还没就绪,
    // 明确回报失败而不是静默丢弃 —— 否则后端那条动作会一直挂在 running。
    await browserBackend
      .report(action.id, { status: "failed", error: "view host not ready" })
      .catch(() => undefined);
    return;
  }
  try {
    if (action.action === "close") {
      views.panelDetach(action.session_id);
      panelled.delete(action.session_id);
      views.destroy(action.session_id);
      await browserBackend.report(action.id, { status: "done", result: {} });
      return;
    }

    const driver = views.registerSession(action.session_id, action.partition);
    // 挂成右下角面板:用户能看见智能体在做什么,同时视图获得真实布局与命中测试(可信输入的前提)。
    // 挂不上(面板已达上限 / 宿主窗口没了)不影响执行 —— RPA 动作走的是 DOM 事件,不依赖布局。
    if (!panelled.has(action.session_id) && views.panelAttach(action.session_id, { idleMs: PANEL_IDLE_MS })) {
      panelled.add(action.session_id);
      plog("browser session panelled:", action.session_id);
    }
    views.touchPanel(action.session_id); // 刷新空闲计时


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
