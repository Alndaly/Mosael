// 发布执行器(Electron 主进程内):轮询后端认领待办 → 为该账号驱动其 WebContentsView 跑平台适配器
// (上传/填表/发表)→ 回报状态。任务状态源在后端,这里只做「浏览器驱动」这件只有 Electron 能做的事。
//
// 并发模型:「跨账号并发、同账号串行 + 前台单槽」。
//  - 发布任务默认在**后台不可见**的账号视图里跑(上传走 CDP、填表走 JS、点击走 sendInputEvent,都
//    不需要视图 attach 到窗口)。同时最多 MAX_CONCURRENT 条(不同账号)。
//  - 一个账号共享一个内嵌视图,不能并发两条任务:认领时把「正在跑的账号」传给后端排除(claimTask)。
//  - 「前台可见槽」至多一个(视图 attach 到窗口):留给需要用户在场的时刻——登录扫码、dry_run 准备好
//    待确认、失败/受阻现场。用 views.visibleAccountId 表达前台是否被占;被占时后台任务不抢,视图仍在,
//    用户可稍后从任务行「查看页面」再亮出来。
import { app, type BaseWindow } from "electron";
import { mkdir } from "node:fs/promises";
import path from "node:path";

// @ts-expect-error CJS 词典无类型声明;esbuild 会内联(tsconfig 不含 electron/)。
import { tr } from "./i18n";
import { AccountViewManager } from "./accountViews";
import { createAdapter } from "./adapters";
import { isAutomationBlockedError } from "./errors";
import { resolvePlatform } from "./platforms";
import type { PublishTask, ViewState } from "./types";
import * as backend from "./backend";

let views: AccountViewManager | null = null;
// 正在跑发布任务(或后台复检)的账号集合:size 即并发数,元素即认领时要排除的账号(同账号串行)。
const running = new Set<string>();
// 有限并发上限:默认 3,可用 MIBU_PUBLISH_CONCURRENCY 覆盖(夹在 1–5)。多账号同时后台发布更快,但
// 同机高频操作对平台风控/机器资源更重,故设上限而非全并发。
const MAX_CONCURRENT = (() => {
  const n = Number.parseInt(process.env.MIBU_PUBLISH_CONCURRENCY || "", 10);
  return Number.isFinite(n) ? Math.min(5, Math.max(1, n)) : 3;
})();
let stopped = false;
// loop() 与登录轮询的「代」:每次 startPublishWorker 自增。stop→reactivate 时旧代在途的迭代/轮询
// 回调据此自我了断,不把自己重新排进定时器,避免复活成不断累积的重复链。
let generation = 0;
// 登录轮询的可取消定时器句柄:stopPublishWorker 要能停掉它(视图销毁后别再空转最多 10 分钟)。
let loginPollTimer: ReturnType<typeof setTimeout> | null = null;

// 一条任务跑到终态/受阻时回调主进程(发系统通知 + 更新 dock 角标)。
export type SettleInfo = { status: string; title: string; accountName: string; dryRun: boolean };
let onSettled: ((info: SettleInfo) => void) | null = null;
function settle(t: PublishTask, status: string, dryRun: boolean): void {
  try {
    onSettled?.({ status, title: t.title, accountName: t.accountName, dryRun });
  } catch {
    /* 通知失败不影响发布主流程 */
  }
}

const POLL_IDLE_MS = 4000;
const POLL_BUSY_MS = 500;
// 每步之间的拟人停顿:随机区间而非固定值(固定节奏本身就是一种自动化特征)。桌面版是 1–3s 随机。
const stepDelay = (): number => 700 + Math.floor(Math.random() * 1100); // 700–1800ms

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** 请求前台可见槽:仅当前台空闲(无视图可见)才把该账号亮出并返回 true;被占则不抢(让当前占用者先
 *  处理完),返回 false——视图仍在(表单/现场都在),用户可稍后从任务行「查看页面」再亮出来。 */
function requestFront(accountId: string): boolean {
  if (!views || views.visibleAccountId) return false;
  views.show(accountId);
  return true;
}

/** 桌面版 resolveBlockedStatus 的等价:AutomationBlockedError → 任务受阻状态;普通异常 → null(失败)。 */
function resolveBlockedStatus(
  error: unknown,
): "waiting_manual" | "login_required" | "permission_required" | "blocked" | null {
  if (!isAutomationBlockedError(error)) return null;
  if (error.reason === "manual_required") return "waiting_manual";
  if (error.reason === "login_required") return "login_required";
  if (error.reason === "permission_required") return "permission_required";
  return "blocked";
}

function toAdapterTask(t: backend.BackendTask): PublishTask {
  return {
    id: t.id,
    accountId: t.account_id,
    accountName: t.account_name,
    platform: resolvePlatform(t.platform).id,
    videoPath: t.video_path,
    title: t.title,
    tags: t.tags || [],
    platformOptions: {
      dryRun: t.dry_run,
      description: t.description || "",
      shortTitle: t.short_title || "",
    },
    scheduledAt: null,
    status: "running",
    errorMessage: null,
    screenshotPath: null,
    createdAt: "",
    updatedAt: "",
  };
}

async function captureFailure(
  taskId: string,
  driver: { screenshot: (p: string) => Promise<void> },
) {
  try {
    const dir = path.join(app.getPath("userData"), "publish-screenshots");
    await mkdir(dir, { recursive: true });
    const file = path.join(dir, `${taskId}-${Date.now()}.png`);
    await driver.screenshot(file);
    return file;
  } catch {
    return null;
  }
}

/** 跑一条发布任务(后台不可见)。完成时从 running 移除。需要用户在场的时刻(准备好待确认 / 失败现场)
 *  请求前台可见槽:抢到就亮出来,抢不到(前台被别的账号占)也没关系——视图仍在,任务行可再亮。 */
async function runTask(bt: backend.BackendTask): Promise<void> {
  if (!views) {
    running.delete(bt.account_id);
    return;
  }
  const t = toAdapterTask(bt);
  const driver = views.getDriver(t.accountId); // ensure 视图(不 show);getDriver 不抛
  try {
    await views.configureAccount(t.accountId, null);
    const adapter = createAdapter(t.platform, driver, t);
    await adapter.openCreatorPage();
    await delay(stepDelay());

    const loggedIn = await adapter.checkLogin();
    if (!loggedIn) {
      await backend.patchAccount(t.accountId, {
        binding_status: "login_required",
        last_error: tr("未登录"),
      });
      await backend.reportTask(t.id, {
        status: "login_required",
        error_message: tr("账号未登录。在发布控制台点该账号「登录」完成扫码后重试。"),
      });
      settle(t, "login_required", t.platformOptions.dryRun === true);
      return;
    }
    await backend.patchAccount(t.accountId, { binding_status: "bound", last_error: null });

    await adapter.uploadVideo(t.videoPath);
    await delay(stepDelay());
    await adapter.fillTitle(t.title);
    await delay(stepDelay());
    await adapter.fillTags(t.tags);
    await delay(stepDelay());

    if (t.platformOptions.dryRun === true) {
      await backend.reportTask(t.id, { status: "prepared" });
      settle(t, "prepared", true);
      // 准备好待确认:请求前台让用户直接确认 / 点真发。抢不到前台也无妨(表单已填好,任务行可再亮)。
      requestFront(t.accountId);
      return;
    }
    await adapter.submit();
    await delay(stepDelay());
    await adapter.waitResult();
    await backend.reportTask(t.id, { status: "success" });
    settle(t, "success", false);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const screenshot = await captureFailure(t.id, driver);
    const blocked = resolveBlockedStatus(error);
    if (blocked === "login_required")
      await backend.patchAccount(t.accountId, {
        binding_status: "login_required",
        last_error: message,
      });
    else if (blocked === "waiting_manual")
      await backend.patchAccount(t.accountId, {
        binding_status: "manual_required",
        last_error: message,
      });
    else if (blocked === "permission_required")
      await backend.patchAccount(t.accountId, {
        binding_status: "permission_required",
        last_error: message,
      });
    await backend.reportTask(t.id, {
      status: blocked ?? "failed",
      error_message: message,
      screenshot_path: screenshot,
    });
    settle(t, blocked ?? "failed", t.platformOptions.dryRun === true);
    // 失败/受阻且现场还在(验证码、审核提示、报错弹窗):请求前台亮出来供用户查看。抢不到就算了,
    // 任务行的「查看页面」可再亮。现场已没了(webContents 已销毁/空白)就不请求。
    const hasLive = (() => {
      try {
        const url = driver.url();
        return Boolean(url) && url !== "about:blank";
      } catch {
        return false; // webContents 已销毁
      }
    })();
    if (hasLive) requestFront(t.accountId);
  } finally {
    running.delete(t.accountId);
    driver.setAbortSignal(null);
    // 后台任务默认从不 show;占了前台的(准备好/失败现场)留着供查看,这里不主动 hide。
  }
}

/** 后台复检某账号登录态:静默打开创作页(不 show 视图)→ checkLogin → 回报 bound/login_required。
 *  「已登录」只是快照,会话会过期、也可能在别处登出——这里定期把 UI 拉回真实状态。复检失败(网络/
 *  导航抖动)不下线用户,保留原状态,下个 ttl 再查。 */
async function checkAccountStatus(acc: backend.CheckAccount): Promise<void> {
  if (!views) return;
  const platform = resolvePlatform(acc.platform).id;
  const stub: PublishTask = {
    id: `check-${acc.account_id}`,
    accountId: acc.account_id,
    accountName: acc.name ?? "",
    platform,
    videoPath: "",
    title: "",
    tags: [],
    platformOptions: { dryRun: true, description: "", shortTitle: "" },
    scheduledAt: null,
    status: "running",
    errorMessage: null,
    screenshotPath: null,
    createdAt: "",
    updatedAt: "",
  };
  try {
    await views.configureAccount(acc.account_id, null);
    const driver = views.getDriver(acc.account_id); // ensure() 建视图但不 show —— 后台静默检查
    const adapter = createAdapter(platform, driver, stub);
    await adapter.openCreatorPage();
    const loggedIn = await adapter.checkLogin();
    await backend.patchAccount(acc.account_id, {
      binding_status: loggedIn ? "bound" : "login_required",
      last_error: loggedIn ? null : tr("登录已失效,请重新登录"),
    });
    // 从「已登录」变「失效」才通知:后台静默复检没有前台现场,用户不主动看发布台就不知道掉线——
    // 补一条系统通知 + dock 角标。对本就 login_required 的账号不重复弹(只认 bound→失效这一次跳变)。
    if (acc.binding_status === "bound" && !loggedIn) {
      settle(stub, "login_required", false);
    }
  } catch {
    // 抖动别误判下线;保留原状态,下个 ttl 再查。
  }
}

async function loop(gen: number): Promise<void> {
  if (stopped || gen !== generation) return;
  let didWork = false; // 这拍干了活(发布/巡检)→ 下拍快轮询,把队列尽快排空
  try {
    await backend.heartbeat();
    // 补发布任务到并发上限。认领时排除正在跑的账号(同账号串行);拿到就后台并发跑(不 await)。
    while (running.size < MAX_CONCURRENT) {
      const { task } = await backend.claimTask([...running]);
      if (!task) break;
      didWork = true;
      running.add(task.account_id);
      void runTask(task).catch(() => running.delete(task.account_id));
    }
    // 没有更多待发任务、且完全空闲(无并发任务、前台无视图占用)时,后台静默复检一个到期账号。
    if (running.size === 0 && !views?.visibleAccountId) {
      const { account } = await backend.claimCheck();
      if (account) {
        didWork = true;
        running.add(account.account_id);
        try {
          await checkAccountStatus(account);
        } finally {
          running.delete(account.account_id);
        }
      }
    }
  } catch {
    // 后端没起来/网络抖动:忽略,下个 tick 再试(执行器可比后端先启动)。
  }
  // 仍是当前代才续排:stop→reactivate 后旧代不复活(新代由 startPublishWorker 另起一条链)。
  if (!stopped && gen === generation)
    setTimeout(() => loop(gen), didWork ? POLL_BUSY_MS : POLL_IDLE_MS);
}

/** 在应用主窗口里启动执行器。onViewChanged 让渲染层知道内嵌视图显示/隐藏(可驱动顶栏留白)。 */
export function startPublishWorker(opts: {
  window: BaseWindow;
  onViewChanged?: (state: ViewState) => void;
  getAccountName?: (accountId: string) => string | null;
  onTaskSettled?: (info: SettleInfo) => void;
}): void {
  if (views) return;
  stopped = false;
  generation += 1; // 新一代:旧代在途的 loop/登录轮询不会复活成重复链
  running.clear();
  onSettled = opts.onTaskSettled ?? null;
  views = new AccountViewManager(opts.onViewChanged);
  views.attachWindow(opts.window, opts.getAccountName ?? (() => null));
  // 开机先来一轮全量巡检:把所有账号标记为待复检,loop 会快速逐个后台核对登录态。
  void backend.markDue().catch(() => undefined);
  loop(generation);
}

export function stopPublishWorker(): void {
  stopped = true;
  // 停掉登录轮询定时器:视图即将销毁,别再让它空转触发(最多 10 分钟)。在途的 checkLogin/loop
  // 迭代靠 generation/stopped 自我了断,不会复活成重复链。
  if (loginPollTimer) {
    clearTimeout(loginPollTimer);
    loginPollTimer = null;
  }
  // 销毁并清空 views,让下次 startPublishWorker 能重新绑定新窗口(mac 关窗→重新激活)。持久化会话
  // 在磁盘分区里(persist:mibu-<id>),销毁视图不丢登录态。
  views?.destroyAll();
  views = null;
  running.clear();
  onSettled = null;
}

/** 结束一次登录轮询:停定时器。若已进入新一代(stop→reactivate),共享状态归新代管,这里不碰。
 *  前台可见槽由 views.visibleAccountId 表达——登录视图留在前台(原行为),用户 Esc/返回自行收起。 */
function endLogin(gen: number): void {
  if (gen !== generation) return;
  if (loginPollTimer) {
    clearTimeout(loginPollTimer);
    loginPollTimer = null;
  }
}

/** 触发某账号登录:亮出其视图、打开登录页,轮询登录态并回写后端(最多 10 分钟)。 */
export async function openLogin(accountId: string, platform: string): Promise<void> {
  if (!views) return;
  // 该账号正有发布任务在后台跑:登录会切它的视图/抢焦点,拒绝,等任务完成。
  if (running.has(accountId)) throw new Error(tr("该账号有发布任务正在进行，请等它完成后再登录"));
  // 前台已被别的账号占(另一个登录 / 待确认现场):拒绝,让用户先处理完前台那个。
  if (views.visibleAccountId && views.visibleAccountId !== accountId)
    throw new Error(tr("有账号正在前台操作，请先处理完再登录"));
  const gen = generation;
  try {
    await views.configureAccount(accountId, null);
    const driver = views.getDriver(accountId);
    views.show(accountId);
    const def = resolvePlatform(platform);
    await backend.patchAccount(accountId, { binding_status: "checking" });
    await driver.goto(def.loginUrl);
    const adapter = createAdapter(platform, driver, {
      id: `login-${accountId}`,
      accountId,
      accountName: "",
      platform: def.id,
      videoPath: "",
      title: "",
      tags: [],
      platformOptions: {},
      scheduledAt: null,
      status: "running",
      errorMessage: null,
      screenshotPath: null,
      createdAt: "",
      updatedAt: "",
    });
    const deadline = Date.now() + 10 * 60 * 1000;
    const poll = async () => {
      loginPollTimer = null;
      // stop/换代/视图销毁/超时:收工,不再续排。
      if (stopped || gen !== generation || !views || Date.now() > deadline) {
        endLogin(gen);
        return;
      }
      let ok = false;
      try {
        ok = await adapter.checkLogin();
      } catch {
        /* 页面还没到位 */
      }
      // checkLogin 挂起期间可能已 stop/换代:再查一次,别对已属新代的共享状态动手或续排。
      if (stopped || gen !== generation || !views) {
        endLogin(gen);
        return;
      }
      if (ok) {
        try {
          await backend.patchAccount(accountId, { binding_status: "bound", last_error: null });
        } catch {
          /* 回写失败下个 ttl 再纠正 */
        }
        endLogin(gen);
        return;
      }
      loginPollTimer = setTimeout(poll, 5000);
    };
    void poll();
  } catch (error) {
    // 打开/导航阶段就失败:收工,再把错误抛给调用方。
    endLogin(gen);
    throw error;
  }
}

/** 手动打开某账号的平台页面:亮出其视图。若该视图已有页面(如刚「仅准备」好的发布表单——hide
 *  只是移除子视图、webContents 与页面都还在),直接恢复,用户可人工确认/真发;否则导航到创作首页。 */
export async function openPage(accountId: string, platform: string): Promise<void> {
  if (!views) return;
  // 前台被别的账号占(登录 / 待确认现场):亮出那个占用者,别抢(切走会打断它)。
  if (views.visibleAccountId && views.visibleAccountId !== accountId) {
    views.show(views.visibleAccountId);
    return;
  }
  await views.configureAccount(accountId, null);
  const driver = views.getDriver(accountId);
  const current = driver.url();
  views.show(accountId);
  if (!current || current === "about:blank") {
    const def = resolvePlatform(platform);
    await driver.goto(def.dashboardUrl || def.loginUrl);
  }
}

/** 收起内嵌视图,把窗口还给 React UI。 */
export function hidePublishView(): void {
  views?.hide();
}
