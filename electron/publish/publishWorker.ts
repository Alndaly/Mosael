// 发布执行器(Electron 主进程内):轮询后端认领待办 → 为该账号驱动其 WebContentsView 跑平台适配器
// (上传/填表/发表)→ 回报状态。任务状态源在后端,这里只做「浏览器驱动」这件只有 Electron 能做的事。
//
// 并发模型:「跨账号并发、同账号串行 + 前台单槽」。
//  - 发布任务默认把账号视图挂成**右下角悬浮面板**(384×240 + zoom 0.3 → 布局仍是 1280×800 桌面版)。
//    挂载 = 参与合成 = 有真实布局与命中测试,于是可信指针输入(isTrusted=true)可用、画面也是真的。
//    多条并发就叠成卡片堆;实测被完全遮挡的那层照样有布局、照样点得中。同时最多 MAX_CONCURRENT 条。
//  - 一个账号共享一个内嵌视图,不能并发两条任务:认领时把「正在跑的账号」传给后端排除(claimTask)。
//  - 「前台可见槽」至多一个(视图 attach 到窗口):留给需要用户在场的时刻——登录扫码、dry_run 准备好
//    待确认、失败/受阻现场。用 views.visibleAccountId 表达前台是否被占;被占时后台任务不抢,视图仍在,
//    用户可稍后从任务行「查看页面」再亮出来。
import { app, type BaseWindow } from "electron";
import { mkdir } from "node:fs/promises";
import path from "node:path";

import { tr } from "./i18n";
import { createSharedViews, destroySharedViews, type AccountViewManager, type PanelCard } from "./accountViews";
import { plog } from "./log";
import { createAdapter } from "./adapters";
import { isAutomationBlockedError } from "./errors";
import { resolvePlatform } from "./platforms";
import type { PageDriver } from "./pageDriver";
import type { LiveViewFrame, PublishTask, ViewState } from "./types";
import * as backend from "./publishBackend";

let views: AccountViewManager | null = null;
// 正在跑「真发布任务」的账号:size 即并发数,元素即认领时要排除的账号(同账号串行)。
const running = new Set<string>();
// 正在后台复检登录态的账号:与 running 分开——否则复检会被误当成"发布任务进行中"挡住用户登录。
const rechecking = new Set<string>();
// 用户已开始登录接管的账号:后台复检遇到它直接放弃,避免和登录抢同一个视图 goto(表现为空白)。
const loginAccounts = new Set<string>();
// 有限并发上限:默认 3,可用 OPEN_STUDIO_PUBLISH_CONCURRENCY 覆盖(夹在 1–5)。多账号同时后台发布更快,但
// 同机高频操作对平台风控/机器资源更重,故设上限而非全并发。
const MAX_CONCURRENT = (() => {
  const n = Number.parseInt(process.env.OPEN_STUDIO_PUBLISH_CONCURRENCY || "", 10);
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

let onFrame: ((frame: LiveViewFrame) => void) | null = null;

const LIVE_TICK_MS = 1000;
// 面板挂不上时的兜底视口尺寸(CDP Emulation)。与面板模式的布局视口(384/0.3 = 1280×800)取同一档,
// 平台页面按桌面版布局,不会掉进移动端/窄屏分支。
const BACKGROUND_VIEWPORT = { width: 1280, height: 800 };
// 连续这么多次取不到画面就放弃取像(见 LiveMirror.tick)。
const CAPTURE_ATTEMPTS = 3;
// 「镜像单槽」:同时最多镜像一个账号。与前台单槽同一个道理——并发时多账号轮流推帧,面板只会来回
// 跳,反而一条都看不清;截图也不便宜,多开纯属浪费。
let mirroring: string | null = null;

/**
 * 任务执行期间把后台账号视图镜像给前端。
 *
 * **画面是尽力而为,步骤文案才是保证项。** Chromium 只为真正参与合成的视图产生像素:
 * electron 冒烟实测,未加入窗口的 WebContentsView 上 screencast 0 帧、capturePage 空图、
 * CDP Page.captureScreenshot 直接挂起;窗口隐藏或被遮挡时同样取不到。而发布任务跑的时候视图
 * 正是「不在窗口里」这个状态——只有失败现场被 requestFront 亮出来后才稳定有画面。
 * (线上确有后台任务成功截到图的例子,所以不是必然失败,但不能当作保证。)
 *
 * 因此这里每拍推一帧,画面拿到就带上、拿不到就只带步骤:哪怕一个像素都没有,用户也能看到
 * 「B站 · 上传视频」停了五分钟——那正是这次故障真正需要被看见的信息。
 */
class LiveMirror {
  private label: string;
  private settled = false;
  private timer: ReturnType<typeof setInterval> | null = null;
  private held = false;
  private capturing = false;
  private captureMisses = 0;
  private captureBroken = false;

  constructor(
    private readonly accountId: string,
    private readonly driver: PageDriver,
    label: string,
  ) {
    this.label = label;
  }

  start(): void {
    if (!onFrame || mirroring) return;
    mirroring = this.accountId;
    this.held = true;
    this.timer = setInterval(() => void this.tick(), LIVE_TICK_MS);
  }

  /** 切换当前步骤文案。光看画面分不清「正在上传」和「卡住了」,步骤名才分得清。
   *  settled 标记终态:面板据此停掉「运行中」的转圈。 */
  step(label: string, settled = false): void {
    this.label = label;
    this.settled = settled;
    if (this.held) void this.tick();
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    if (!this.held) return;
    this.held = false;
    if (mirroring === this.accountId) mirroring = null;
  }

  private async tick(): Promise<void> {
    if (!onFrame || !this.held || this.capturing) return;
    let dataUrl: string | undefined;
    // 已挂成悬浮面板时,真实画面就在屏幕右下角,再截一遍纯属浪费(capturePage 不便宜,
    // 而且在这种视图上曾经把渲染状态搞坏过)。此时只推步骤文案。
    if (views?.isPanelled(this.accountId)) {
      this.push(undefined);
      return;
    }
    // 连续取不到就彻底放弃取像,后面只推文字。
    //
    // captureBase64 对 capturePage 做了竞速超时,但超时只结束**我们这边的 promise** —— 底层请求
    // 仍挂在那个 webContents 上。后台视图根本不产生像素,于是每秒攒一个永不完成的请求,一条任务
    // 下来几十个,足以把渲染状态搞坏:任务结束后用户点「查看页面」看到的是**白屏**。
    // 试够 CAPTURE_ATTEMPTS 次仍拿不到,就认定这个视图这轮取不到像素,不再骚扰它。
    if (this.captureBroken) {
      this.push(undefined);
      return;
    }
    this.capturing = true;
    try {
      dataUrl = (await this.driver.captureBase64()) ?? undefined;
      this.captureMisses = dataUrl ? 0 : this.captureMisses + 1;
      if (!dataUrl && this.captureMisses >= CAPTURE_ATTEMPTS) {
        this.captureBroken = true;
        plog("live mirror: 放弃取像(视图不产生像素),后续只推步骤文案", this.accountId);
      }
    } catch {
      /* 镜像是观测手段,不是发布的一部分:取不到就只推文字,绝不连累任务 */
      this.captureMisses += 1;
    } finally {
      this.capturing = false;
    }
    this.push(dataUrl);
  }

  private push(dataUrl: string | undefined): void {
    if (!onFrame || !this.held) return;
    let url: string | undefined;
    try {
      url = this.driver.url();
    } catch {
      /* webContents 已销毁 */
    }
    onFrame({ sessionId: this.accountId, dataUrl, label: this.label, url, settled: this.settled });
  }
}
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
    plog("runTask aborted (views=null):", bt.id);
    running.delete(bt.account_id);
    return;
  }
  plog("runTask start:", bt.id, bt.platform, bt.video_path);
  const t = toAdapterTask(bt);
  const driver = views.getDriver(t.accountId); // ensure 视图(不 show);getDriver 不抛
  const platformLabel = resolvePlatform(t.platform).label;
  const mirror = new LiveMirror(t.accountId, driver, `${platformLabel} · ${tr("准备中")}`);
  // 每一步同时进日志和实时窗口。这段之前完全不留痕:一次「表单填好了却没投出去」的故障,日志里
  // 只表现为 checkLogin 之后静默五分钟,画面上也什么都看不到,无从判断卡在上传、填表还是提交。
  const step = (label: string, settled = false): void => {
    plog("runTask step:", bt.id, label);
    mirror.step(`${platformLabel} · ${label}`, settled);
  };
  try {
    // 把视图挂成右下角悬浮面板:参与合成 → 有真实布局与命中测试 → **可信指针输入可用**,
    // 而且画面是真的(不必再截图镜像)。挂不上(窗口没了)时退回 CDP 视口覆盖:那样至少有布局,
    // 点击会自动降级到 DOM 事件。
    views.panelAttach(t.accountId);
    if (!views.isPanelled(t.accountId)) {
      await driver.setMetricsOverride(BACKGROUND_VIEWPORT.width, BACKGROUND_VIEWPORT.height);
    }
    mirror.start();
    await views.configureAccount(t.accountId, bt.proxy);
    const adapter = createAdapter(t.platform, driver, t);
    step(tr("打开创作页"));
    await adapter.openCreatorPage();
    plog("runTask creator page opened:", bt.id, driver.url());
    await delay(stepDelay());

    step(tr("检查登录态"));
    const loggedIn = await adapter.checkLogin();
    plog("runTask checkLogin:", bt.id, loggedIn);
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

    step(tr("上传视频"));
    await adapter.uploadVideo(t.videoPath);
    await delay(stepDelay());
    step(tr("填写标题"));
    await adapter.fillTitle(t.title);
    await delay(stepDelay());
    step(tr("填写标签与简介"));
    await adapter.fillTags(t.tags);
    await delay(stepDelay());

    if (t.platformOptions.dryRun === true) {
      step(tr("已填好,待确认"));
      await backend.reportTask(t.id, { status: "prepared" });
      settle(t, "prepared", true);
      // 准备好待确认:请求前台让用户直接确认 / 点真发。抢不到前台也无妨(表单已填好,任务行可再亮)。
      requestFront(t.accountId);
      return;
    }
    step(tr("提交投稿"));
    await adapter.submit();
    await delay(stepDelay());
    step(tr("等待平台确认"));
    await adapter.waitResult();
    step(tr("发布成功"), true);
    await backend.reportTask(t.id, { status: "success" });
    plog("runTask success:", t.id);
    settle(t, "success", false);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    plog("runTask error:", t.id, error instanceof Error ? error : message);
    // 让实时窗口停在失败那一刻的画面与步骤上,而不是无声消失。
    mirror.step(`${platformLabel} · ${tr("失败")}`, true);
    // 回报失败是这一段里**唯一不能被跳过**的事:它没送到,后端就永远停在 running,前台看到的是
    // 「一直在跑」。所以它前面的每一步都必须既有界又不抛 —— 线上就出过 captureFailure 里
    // capturePage 挂死、把回报一起拖没的情况(见 PageDriver.screenshot 的注释)。
    const screenshot = await captureFailure(t.id, driver);
    const blocked = resolveBlockedStatus(error);
    const bindingStatus =
      blocked === "login_required"
        ? "login_required"
        : blocked === "waiting_manual"
          ? "manual_required"
          : blocked === "permission_required"
            ? "permission_required"
            : null;
    if (bindingStatus) {
      await backend
        .patchAccount(t.accountId, { binding_status: bindingStatus, last_error: message })
        .catch((patchError: unknown) =>
          plog("runTask patchAccount failed (报告继续):", t.id, String(patchError).slice(0, 120)),
        );
    }
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
    mirror.stop();
    // 撤面板 + 撤视口覆盖:任务结束后视图可能被用户从「查看页面」亮出来,带着面板缩放或覆盖
    // 都会和窗口尺寸对不上。panelDetach 会顺手把 zoomFactor 还原成 1(它按 origin 持久化)。
    views?.panelDetach(t.accountId);
    await driver.clearMetricsOverride().catch(() => undefined);
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
  // 用户已开始登录接管:放弃本次复检,别和登录抢同一个视图 goto。放弃也要把认领时写下的
  // checking 放回去 —— 认领了不回报,账号就挂在「检测中」出不来(与 loop 里那条同一个理由)。
  if (loginAccounts.has(acc.account_id)) {
    await backend
      .patchAccount(acc.account_id, { binding_status: acc.binding_status ?? "unknown" })
      .catch(() => undefined);
    return;
  }
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
    plog("recheck start:", acc.account_id, platform);
    await views.configureAccount(acc.account_id, acc.proxy ?? null);
    const driver = views.getDriver(acc.account_id); // ensure() 建视图但不 show —— 后台静默检查
    const adapter = createAdapter(platform, driver, stub);
    await adapter.openCreatorPage();
    const loggedIn = await adapter.checkLogin();
    plog("recheck result:", acc.account_id, loggedIn ? "bound" : "login_required");
    await backend.patchAccount(acc.account_id, {
      binding_status: loggedIn ? "bound" : "login_required",
      last_error: loggedIn ? null : tr("登录已失效,请重新登录"),
    });
    // 从「已登录」变「失效」才通知:后台静默复检没有前台现场,用户不主动看发布台就不知道掉线——
    // 补一条系统通知 + dock 角标。对本就 login_required 的账号不重复弹(只认 bound→失效这一次跳变)。
    if (acc.binding_status === "bound" && !loggedIn) {
      settle(stub, "login_required", false);
    }
  } catch (error) {
    // 抖动别误判下线;把账号翻回复检前的状态(绝不能留在 checking——那不在任何
    // 认领条件里,会永久卡死),下个 ttl 再查。
    plog("recheck error:", acc.account_id, error instanceof Error ? error : String(error));
    await backend
      .patchAccount(acc.account_id, {
        binding_status: acc.binding_status && acc.binding_status !== "checking" ? acc.binding_status : "unknown",
        last_error: null,
      })
      .catch(() => undefined);
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
      plog("claimed:", task.id, task.platform, "account:", task.account_id);
      didWork = true;
      running.add(task.account_id);
      void runTask(task).catch((error) => {
        // runTask 自身兜底了 report;走到这说明兜底之前就炸了(如 toAdapterTask)——必须留痕。
        plog("runTask crashed before report:", task.id, error instanceof Error ? error : String(error));
        running.delete(task.account_id);
      });
    }
    // 没有更多待发任务、且完全空闲(无发布/复检并发、前台无视图占用)时,后台静默复检一个到期账号。
    if (running.size === 0 && rechecking.size === 0 && !views?.visibleAccountId) {
      const { account } = await backend.claimCheck();
      // 用户正在登录接管的账号跳过复检(否则抢同一个视图 goto → 空白)。但**认领已经把它翻成
      // checking 了** —— 跳过就等于认领了不回报,账号会挂在「检测中」直到 10 分钟的悬挂自愈。
      // 不查就得放回去。
      if (account && loginAccounts.has(account.account_id)) {
        await backend
          .patchAccount(account.account_id, { binding_status: account.binding_status ?? "unknown" })
          .catch(() => undefined);
      } else if (account) {
        didWork = true;
        rechecking.add(account.account_id);
        try {
          await checkAccountStatus(account);
        } finally {
          rechecking.delete(account.account_id);
        }
      }
    }
  } catch (error) {
    // 后端没起来/网络抖动:下个 tick 再试(执行器可比后端先启动)。连接拒绝不刷屏,其他错误留痕。
    const msg = error instanceof Error ? error.message : String(error);
    if (!/fetch failed|ECONNREFUSED|aborted/i.test(msg)) plog("loop error:", msg);
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
  onFrame?: (frame: LiveViewFrame) => void;
  /** 悬浮卡片几何变化 —— 渲染层照它画圆角/阴影/标题条(原生 View 画不了)。 */
  onPanels?: (cards: PanelCard[]) => void;
}): void {
  if (views) return;
  stopped = false;
  generation += 1; // 新一代:旧代在途的 loop/登录轮询不会复活成重复链
  running.clear();
  onSettled = opts.onTaskSettled ?? null;
  onFrame = opts.onFrame ?? null;
  // 共享实例:浏览器(RPA/智能体)执行器用的是同一个管理器(见 accountViews.createSharedViews)。
  views = createSharedViews(opts.onViewChanged, opts.onPanels);
  views.attachWindow(opts.window, opts.getAccountName ?? (() => null));
  plog("worker started, generation", generation);
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
  // 在磁盘分区里(persist:openstudio-<id>),销毁视图不丢登录态。
  destroySharedViews();
  views = null;
  onFrame = null;
  mirroring = null;
  running.clear();
  onSettled = null;
}

/**
 * 结束一次登录轮询:停定时器,并且**把过渡态收干净**。
 *
 * openLogin 一进来就把账号写成 `checking`(界面显示「检测中」),而在此之前只有"登录成功"这一条
 * 路把它改回去 —— 超时、用户放弃、导航失败三个出口都把它留在 checking。而 checking 不在任何认领
 * 条件里(要等满 10 分钟的悬挂自愈),于是卡片就一直转:线上 TikTok 那条正是这样,日志里只有
 * 反复的登录页 goto,一条 recheck start 都没有。
 *
 * 没登上就写回 `unknown` —— 字面意思就是「还不知道」,是此刻唯一诚实的值,而且它**立刻可被复检
 * 认领**(claim_check 的第一个条件),下一拍就会去问出真实状态。不猜 bound,也不武断判 login_required。
 */
function endLogin(gen: number, accountId?: string, loggedIn = false): void {
  if (accountId) loginAccounts.delete(accountId);
  if (accountId && !loggedIn) {
    void backend
      .patchAccount(accountId, { binding_status: "unknown" })
      .catch(() => undefined); // 回写失败:下个 ttl 的复检照样会纠正
  }
  if (gen !== generation) return;
  if (loginPollTimer) {
    clearTimeout(loginPollTimer);
    loginPollTimer = null;
  }
}

/** 浏览器池通用档案登录:复用发布账号那套**内嵌视图**(AccountViewManager.openView),在该档案分区
 *  亮出登录页,不弹外部系统窗。与 openLogin 一样占前台单槽——已有视图在前台则拒绝。viewId = 分区名。
 *  通用档案没有平台适配器/登录态轮询,登不登成由用户自己判断(cookie 落分区即可)。 */
export async function openPoolLogin(opts: {
  partition: string;
  url: string;
  name?: string;
  proxy?: string | null;
}): Promise<void> {
  if (!views) throw new Error(tr("发布器未就绪"));
  if (views.visibleAccountId && views.visibleAccountId !== opts.partition)
    throw new Error(tr("有账号正在前台操作，请先处理完再登录"));
  await views.openView({
    viewId: opts.partition,
    partition: opts.partition,
    name: opts.name,
    url: opts.url,
    proxy: opts.proxy ?? null,
  });
}

/** 渲染层重新加载之后,把当前内嵌视图状态补播一次(见 AccountViewManager.republish)。 */
export function republishViewState(): void {
  views?.republish();
}

/** 内嵌视图此刻是否占着前台 —— 主进程据此决定 ⌘R 刷的是内嵌页面还是应用本身。 */
export function embeddedViewVisible(): boolean {
  return Boolean(views?.visibleAccountId);
}

/** 触发某账号登录:亮出其视图、打开登录页,轮询登录态并回写后端(最多 10 分钟)。 */
export async function openLogin(accountId: string, platform: string): Promise<void> {
  if (!views) return;
  // 该账号正有「真发布任务」在后台跑:登录会切它的视图/抢焦点,拒绝,等任务完成。
  // 注意:后台复检(rechecking)不在此列——复检恰恰是为确认登录态,用户手动登录优先级更高,可抢占。
  if (running.has(accountId)) throw new Error(tr("该账号有发布任务正在进行，请等它完成后再登录"));
  // 前台已被别的账号占(另一个登录 / 待确认现场):拒绝,让用户先处理完前台那个。
  if (views.visibleAccountId && views.visibleAccountId !== accountId)
    throw new Error(tr("有账号正在前台操作，请先处理完再登录"));
  // 登录接管:标记后,在飞的复检(若有)遇到它会放弃回写;并中止该视图在飞的 goto/evaluate,
  // 避免复检的旧 goto 与登录的新 goto 互相 abort 把页面留成空白。
  loginAccounts.add(accountId);
  const gen = generation;
  try {
    await views.configureAccount(accountId, await backend.accountProxy(accountId));
    const driver = views.getDriver(accountId);
    // 亮出视图即占据前台单槽,loop 不再对该账号启动新复检;在飞的旧复检 goto 会被下面
    // 登录 goto 的 loadURL 自然覆盖(ERR_ABORTED),不会与登录页互抢。
    views.show(accountId);
    const def = resolvePlatform(platform);
    await backend.patchAccount(accountId, { binding_status: "checking" });
    // 不 await 整页加载:视图已亮出(用户能看到加载中),导航是 fire-and-forget,
    // 让 openLogin 立即返回 → IPC/登录按钮秒解除,不再"卡一阵子"。poll 轮询接管登录态判断。
    void driver.goto(def.loginUrl).catch((error) => plog("login goto error:", accountId, String(error).slice(0, 120)));
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
        endLogin(gen, accountId);
        return;
      }
      // 用户把这个视图收起来了(返回 / 双击 Esc / 切去别的账号)= 他不打算登了。继续轮询没有意义,
      // 而且 loginAccounts 里挂着它会让复检一直跳过这个账号 —— 状态就永远停在「检测中」。
      if (views.visibleAccountId !== accountId) {
        endLogin(gen, accountId);
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
        endLogin(gen, accountId);
        return;
      }
      if (ok) {
        try {
          await backend.patchAccount(accountId, { binding_status: "bound", last_error: null });
        } catch {
          /* 回写失败下个 ttl 再纠正 */
        }
        // 登上了 = 这个内嵌浏览器的差事办完了,自己收回去。此前它会一直挂在前台,用户得再点一次
        // 「返回 Open Studio」才能回来 —— 而他刚做完的事本来就以"回到账号池看到已登录"为终点。
        if (views?.visibleAccountId === accountId) views.hide();
        endLogin(gen, accountId, true);
        return;
      }
      loginPollTimer = setTimeout(poll, 5000);
    };
    void poll();
  } catch (error) {
    // 打开/导航阶段就失败:收工,再把错误抛给调用方。
    endLogin(gen, accountId);
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
  await views.configureAccount(accountId, await backend.accountProxy(accountId));
  const driver = views.getDriver(accountId);
  const current = driver.url();
  views.show(accountId);
  if (!current || current === "about:blank") {
    const def = resolvePlatform(platform);
    await driver.goto(def.dashboardUrl || def.loginUrl);
  }
}

/** 打开某账号内嵌视图的 DevTools(调试平台适配器/巡检选择器用)。先确保视图存在、
 *  必要时亮出并导航到平台页,再挂 detached 检查器;再点一次则关闭。 */
export async function inspectAccount(accountId: string, platform: string): Promise<boolean> {
  if (!views) return false;
  // 前台被别的账号占(登录/待确认现场)→ 别抢,直接给那个视图开检查器。
  if (views.visibleAccountId && views.visibleAccountId !== accountId) {
    return views.openDevTools(views.visibleAccountId);
  }
  await views.configureAccount(accountId, await backend.accountProxy(accountId));
  const driver = views.getDriver(accountId);
  const current = driver.url();
  views.show(accountId);
  if (!current || current === "about:blank") {
    const def = resolvePlatform(platform);
    await driver.goto(def.dashboardUrl || def.loginUrl);
  }
  return views.openDevTools(accountId);
}

/** 内嵌浏览器工具栏:导航当前可见视图。 */
export function navigateView(url: string): void {
  views?.navigate(url);
}
export function viewBack(): void {
  views?.back();
}
export function viewForward(): void {
  views?.forward();
}
export function viewReload(): void {
  views?.reload();
}

/** 收起内嵌视图,把窗口还给 React UI。 */
/** 渲染层拖动/缩放悬浮面板后落到这里(几何由主进程持有:layout() 要用,还要落盘)。 */
export function setPanelLayout(patch: { x?: number; y?: number; width?: number; height?: number }): void {
  views?.setPanelLayout(patch);
}

/** 手动关闭某块悬浮面板:只撤面板,任务/会话照常继续跑(它不依赖面板)。 */
export function closePanel(id: string): void {
  views?.panelDetach(id);
}

export function hidePublishView(): void {
  views?.hide();
}
