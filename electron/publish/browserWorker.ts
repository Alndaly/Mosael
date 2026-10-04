// 浏览器自动化 worker:与发布 worker 并列的第二个拉取循环。轮询 /api/browser/worker/claim 认领动作,
// 在会话隔离的内嵌视图上执行,回报结果。
//
// 会话视图与发布账号视图**共用同一套** AccountViewManager(见 accountViews 的 createSharedViews):
// 同一套内嵌视图、同一套右下角面板叠放、同一套可信输入。此前 RPA 自己起离屏(OSR)BrowserWindow 并
// 定时截帧推给前端做预览 —— 那是"看不见就只能截图"时代的产物。现在动作到来时把视图挂成面板:
// 画面是真实渲染的(不必截帧),而且视图参与合成之后**可信指针输入可用**,智能体的点击不再只有
// isTrusted=false 那一条路。分区照旧严格隔离:ephemeral-*(内存态)/ persist:rpa-* 与发布的
// persist:mosael-* 互不相干。
//
// **不同会话并发,同一会话串行。** 此前一次只跑一个动作:一个会话上「等 60 秒出现登录框」,别的会话
// 上的点击全部干等,而且等的时间都算进了它们自己的超时。现在一次最多领 MAX_INFLIGHT 条、各跑各的;
// 同一会话的串行由后端认领时保证(它不发一个还有动作在跑的会话上的下一条),这里再按会话排一次队兜底。
import { app } from "electron";

import { sharedViews } from "./accountViews";
import { captureForAction } from "./actionCapture";
import { pageForAction } from "./actionPage";
import { dropActionDownloads, saveActionDownloads } from "./actionDownloads";
import { executeBrowserAction, type ActionOutcome } from "./browserActions";
import { browserBackend, type ClaimedAction } from "./browserBackend";
import { plog } from "./log";
import { t } from "../i18n.cjs";
import { applyPartitionMove } from "./partitionMoves";

const IDLE_MS = 1200;
/**
 * 会话面板的空闲自动关闭时长。智能体用完浏览器往往**不发 close 动作**就去干别的了,面板就会一直
 * 占着;每个动作 touch 一次,超过这个时长没动作就自动撤。发布任务不设这个(它在 finally 里显式撤)——
 * 因为发布会在 waitResult 里合理地静默十几分钟,按空闲扫会把还在跑的任务收掉。
 */
const PANEL_IDLE_MS = 90_000;
const BUSY_MS = 150;
/** 同时在跑的动作上限。每条都挂一个视图面板,再多屏幕上也看不过来。 */
const MAX_INFLIGHT = 4;
/**
 * 心跳间隔。ADR-0002 的契约是「至少每 20 秒一次」,租约 60 秒。**心跳自己一条循环**,不夹在动作之间:
 * 此前它在认领循环里、动作之间才发,一个跑了 70 秒的等待就让自己的租约过期、被后端判成执行器失联。
 */
const HEARTBEAT_MS = 20_000;
const delay = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

let generation = 0; // 递增即令旧 loop 自然退出
// 本 worker 挂过面板的会话,停机时要撤干净(视图本身归共享管理器,不在这里销毁)。
const panelled = new Set<string>();
/** 在跑的动作 → 它的中止开关。心跳说这条已经不归我了(后端放弃了它、租约被判过期),就中止它。 */
const running = new Map<string, AbortController>();
/** 每个会话上最后一条动作的尾巴:同一会话的下一条接在它后面。 */
const sessionTails = new Map<string, Promise<void>>();
/** 这个进程用过的分区。搬分区目录要避开它们(见 partitionMoves)。 */
const usedPartitions = new Set<string>();
/**
 * 这台电脑上还等着搬进来的新分区(搬家单因为分区正被这个进程用着而推迟了)。搬成之前不在它上面开视图:
 * 一开就建出空目录,旧登录再也搬不过去。只在同一进程里重启执行器、后端又刚写下搬家单时才会有。
 */
const awaitingMove = new Set<string>();

export function startBrowserWorker(): void {
  stopBrowserWorker();
  const gen = ++generation;
  plog("browser worker started, generation", gen);
  void loop(gen);
  void heartbeatLoop(gen);
}

export function stopBrowserWorker(): void {
  generation++;
  const views = sharedViews();
  for (const sessionId of panelled) views?.panelDetach(sessionId);
  panelled.clear();
  for (const controller of running.values()) controller.abort();
  running.clear();
  sessionTails.clear();
}

async function loop(gen: number): Promise<void> {
  let moved = false;
  while (gen === generation) {
    let didWork = false;
    try {
      // 先搬完登录分区,再开始认领:反过来的话,一条动作先在新分区上建出空目录,旧登录就搬不过去了。
      if (!moved) moved = await movePartitions();
      // 调用方不等了的那些(运行停下、超时):这一拍就停手。只靠心跳要等最多 20 秒 —— 那段时间里它还在页面上
      // 接着点、接着等,而失败现场的截图排在同一会话上它的后面。
      if (running.size) abandon(await browserBackend.abandoned(), "abandoned by the backend");
      if (moved && running.size < MAX_INFLIGHT) {
        const action = await browserBackend.claim();
        if (action && gen === generation) {
          didWork = true;
          schedule(action);
        }
      }
    } catch (error) {
      plog("browser worker loop error:", error instanceof Error ? error.message : String(error));
    }
    await delay(didWork ? BUSY_MS : IDLE_MS);
  }
}

async function heartbeatLoop(gen: number): Promise<void> {
  while (gen === generation) {
    try {
      // 心跳带着手上那些动作去续约,并把**没续上**的还回来 —— 那几条已经不归我了
      // (被判过期、被后端放弃、或被别的执行器接走),接着干只会盖掉别人正在干的那一份:中止它们。
      abandon(await browserBackend.heartbeat(), "lease lost");
    } catch (error) {
      plog("browser heartbeat error:", error instanceof Error ? error.message : String(error));
    }
    await delay(HEARTBEAT_MS);
  }
}

function abandon(ids: string[], why: string): void {
  for (const id of ids) {
    plog(`browser action ${why}, stopping:`, id);
    running.get(id)?.abort();
  }
}

/** 接到这个会话的队尾,不等它跑完 —— 认领循环接着去领别的会话的动作。 */
function schedule(action: ClaimedAction): void {
  const controller = new AbortController();
  running.set(action.id, controller);
  const previous = sessionTails.get(action.session_id) ?? Promise.resolve();
  const tail = previous
    .then(() => handleAction(action, controller.signal))
    .finally(() => {
      running.delete(action.id);
      if (sessionTails.get(action.session_id) === tail) sessionTails.delete(action.session_id);
    });
  sessionTails.set(action.session_id, tail);
}

async function movePartitions(): Promise<boolean> {
  const moves = await browserBackend.partitionMoves();
  const userData = app.getPath("userData");
  for (const move of moves) {
    const result = applyPartitionMove(userData, move, (partition) => usedPartitions.has(partition));
    if (result.status === "absent") continue; // 这台电脑上没有那份登录:不回话,别的电脑还要搬它
    if (result.status === "deferred") {
      awaitingMove.add(move.new_partition);
      plog("browser partition move deferred (in use):", move.old_partition, "→", move.new_partition);
      continue;
    }
    awaitingMove.delete(move.new_partition);
    plog("browser partition move:", move.old_partition, "→", move.new_partition, result.status, result.reason);
    await browserBackend.settlePartitionMove(move.id, result);
  }
  return true;
}

async function handleAction(action: ClaimedAction, signal: AbortSignal): Promise<void> {
  const views = sharedViews();
  if (!views) {
    // 共享视图管理器由发布执行器创建(startPublishWorker)。它没起来说明宿主窗口还没就绪,
    // 明确回报失败而不是静默丢弃 —— 否则后端那条动作会一直挂在 running。
    await browserBackend
      .report(action.id, { status: "failed", error: "view host not ready" })
      .catch(() => undefined);
    return;
  }
  if (signal.aborted) return;
  try {
    if (action.action === "close") {
      views.panelDetach(action.session_id);
      panelled.delete(action.session_id);
      views.destroy(action.session_id);
      await browserBackend.report(action.id, { status: "done", result: {} });
      return;
    }

    if (awaitingMove.has(action.partition)) {
      await browserBackend.report(action.id, { status: "failed", error: t("browserErr_partitionAwaitingMove") });
      return;
    }
    usedPartitions.add(action.partition);
    const driver = views.registerSession(action.session_id, action.partition);
    // 挂成右下角面板:用户能看见智能体在做什么,同时视图获得真实布局与命中测试(可信输入的前提)。
    // 挂不上(面板已达上限 / 宿主窗口没了)不影响执行 —— RPA 动作走的是 DOM 事件,不依赖布局。
    if (!panelled.has(action.session_id) && views.panelAttach(action.session_id, { idleMs: PANEL_IDLE_MS })) {
      panelled.add(action.session_id);
      plog("browser session panelled:", action.session_id);
    }
    views.touchPanel(action.session_id); // 刷新空闲计时

    // 同一会话串行,所以这个会话的 driver 此刻只服务这一条:中止开关挂上去,跑完摘掉。
    driver.setAbortSignal(signal);
    // 这一步里开始的下载归这一步:不弹保存框,做完交给后端入库,素材 id 放进结果(见 actionDownloads)。
    const downloads = views.downloads.collect(action.session_id);
    try {
      let outcome: ActionOutcome;
      try {
        // 「截图」节点:截这一页、存进素材库(和顶栏截屏同一份实现,见 actionCapture);「切换页面」节点:
        // 在会话的几个页面之间切换 / 关掉当前页(见 actionPage)。别的动作照旧交给驱动。
        outcome =
          action.action === "capture"
            ? await captureForAction({
                actionId: action.id,
                webContents: views.contentsOf(action.session_id),
                args: action.args,
              })
            : action.action === "page"
              ? pageForAction(views, action.session_id, action.args)
              : await executeBrowserAction(driver, action.action, action.args);
      } catch (error) {
        await dropActionDownloads(downloads);
        throw error;
      }
      const saved = await saveActionDownloads({
        actionId: action.id,
        action: action.action,
        collector: downloads,
        signal,
        stillLoading: () => views.awaitingResponse(action.session_id),
      });
      await browserBackend.report(action.id, {
        status: "done",
        result: {
          ...(outcome.value !== undefined ? { value: outcome.value } : {}),
          ...(saved.length ? { downloads: saved } : {}),
        },
        last_url: outcome.lastUrl,
      });
    } finally {
      driver.setAbortSignal(null);
    }
    plog("browser action done:", action.action, action.session_id);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    plog("browser action failed:", action.action, message);
    await browserBackend.report(action.id, { status: "failed", error: message }).catch(() => undefined);
  }
}
