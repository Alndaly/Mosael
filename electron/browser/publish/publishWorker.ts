// 发布执行器(Electron 主进程内):轮询后端认领待办 → 为该账号驱动其 WebContentsView 跑平台适配器
// (上传/填表/发表)→ 回报状态。任务状态源在后端,这里只做「浏览器驱动」这件只有 Electron 能做的事。
//
// 并发模型:「跨账号并发、同账号串行 + 前台单槽」。
//  - 发布任务默认把账号视图挂成**右下角悬浮面板**(宽 384、高按页面比例算出,zoom = 视图宽 / 1280
//    → 布局仍是 1280×800 桌面版,见 panelGeometry)。
//    挂载 = 参与合成 = 有真实布局与命中测试,于是可信指针输入(isTrusted=true)可用、画面也是真的。
//    多条并发就叠成卡片堆;实测被完全遮挡的那层照样有布局、照样点得中。同时最多 MAX_CONCURRENT 条。
//  - 一个账号共享一个内嵌视图,不能并发两条任务:认领时把「正在跑的账号」传给后端排除(claimTask)。
//  - 「前台可见槽」至多一个(视图 attach 到窗口):留给需要用户在场的时刻——登录扫码、
//    失败/受阻现场。用 views.visibleAccountId 表达前台是否被占;被占时后台任务不抢,视图仍在,
//    用户可稍后从任务行「查看页面」再亮出来。
import { app } from "electron";

import { t as tr } from "../../i18n.cjs";
import { hostedViews } from "../views/viewHost";
import { plog } from "../log";
import { createAdapter } from "./adapters";
import { platformName, resolvePlatform } from "./platforms";
//: 登录的显式状态机与结构化日志(P3 / P7):失败时要能一眼看出停在哪一步、为什么停。
import { createLoginFlow } from "./loginPhase.cjs";
import { createTrace } from "../trace.cjs";
import type { PageDriver } from "../driver/pageDriver";
import type { LiveViewFrame } from "../types";
import type { PublishTask } from "./publishTypes";
import * as backend from "./publishBackend";
import { runPublishTask } from "./runPublishTask";

let started = false;
// 正在跑「真发布任务」的账号 → 那一条任务 id:size 即并发数,key 即认领时要排除的账号(同账号串行),
// value 是心跳要报给后端的在飞任务(后端拿它续 updated_at,避免长任务被当成悬挂)。
const running = new Map<string, string>();
const taskControllers = new Map<string, AbortController>();
// 正在后台复检登录态的账号:与 running 分开——否则复检会被误当成"发布任务进行中"挡住用户登录。
const rechecking = new Set<string>();
// 用户已开始登录接管的账号:后台复检遇到它直接放弃,避免和登录抢同一个视图 goto(表现为空白)。
const loginAccounts = new Set<string>();
// 有限并发上限:默认 3,可用 MOSAEL_PUBLISH_CONCURRENCY 覆盖(夹在 1–5)。多账号同时后台发布更快,但
// 同机高频操作对平台风控/机器资源更重,故设上限而非全并发。
const MAX_CONCURRENT = (() => {
  const n = Number.parseInt(process.env.MOSAEL_PUBLISH_CONCURRENCY || "", 10);
  return Number.isFinite(n) ? Math.min(5, Math.max(1, n)) : 3;
})();
let stopped = false;
// loop() 与登录轮询的「代」:每次 startPublishWorker 自增。stop→reactivate 时旧代在途的迭代/轮询
// 回调据此自我了断,不把自己重新排进定时器,避免复活成不断累积的重复链。
let generation = 0;
// 登录轮询的可取消定时器句柄:stopPublishWorker 要能停掉它(视图销毁后别再空转最多 10 分钟)。
let loginPollTimer: ReturnType<typeof setTimeout> | null = null;

// 一条任务跑到终态/受阻时回调主进程(发系统通知 + 更新 dock 角标)。
export type SettleInfo = { status: string; title: string; accountName: string };
let onSettled: ((info: SettleInfo) => void) | null = null;

let onFrame: ((frame: LiveViewFrame) => void) | null = null;

const LIVE_TICK_MS = 1000;
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
 * 正是「不在窗口里」这个状态(只有需要人当场处理的那几档才 requestFront 亮出来)。
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
    if (hostedViews()?.isPanelled(this.accountId)) {
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
        plog("live mirror: giving up on capture (the view produces no pixels); pushing step labels only", this.accountId);
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
function settle(t: PublishTask, status: string): void {
  try {
    onSettled?.({ status, title: t.title, accountName: t.accountName });
  } catch {
    /* 通知失败不影响发布主流程 */
  }
}

const POLL_IDLE_MS = 4000;
const POLL_BUSY_MS = 500;

/** 请求前台可见槽:仅当前台空闲(无视图可见)才把该账号亮出并返回 true;被占则不抢(让当前占用者先
 *  处理完),返回 false——视图仍在(表单/现场都在),用户可稍后从任务行「查看页面」再亮出来。 */
function requestFront(accountId: string): boolean {
  const views = hostedViews();
  if (!views || views.visibleAccountId) return false;
  views.show(accountId);
  return true;
}

async function runTask(bt: backend.BackendTask): Promise<void> {
  //: 视图归视图宿主(views/viewHost),每次现取 —— 宿主重建之后不攥着一份旧的。
  const views = hostedViews();
  if (!views) {
    plog("runTask aborted (views=null):", bt.id);
    running.delete(bt.account_id);
    return;
  }
  const taskViews = views;
  const driver = taskViews.getDriver(bt.account_id);
  const platformLabel = platformName(resolvePlatform(bt.platform).id);
  const mirror = new LiveMirror(bt.account_id, driver, `${platformLabel} · ${tr("publishStep_preparing")}`);
  const controller = new AbortController();
  taskControllers.set(bt.account_id, controller);
  try {
    await runPublishTask(bt, {
      views: taskViews,
      driver,
      mirror,
      controller,
      trace,
      isStopped: () => stopped,
      onSettled: settle,
      requestFront,
    });
  } finally {
    mirror.stop();
    if (taskControllers.get(bt.account_id) === controller) {
      taskControllers.delete(bt.account_id);
      running.delete(bt.account_id);
      driver.setAbortSignal(null);
    }
  }
}

/** 后台复检某账号登录态:静默打开创作页(不 show 视图)→ checkLogin → 回报 bound/login_required。
 *  「已登录」只是快照,会话会过期、也可能在别处登出——这里定期把 UI 拉回真实状态。复检失败(网络/
 *  导航抖动)不下线用户,保留原状态,下个 ttl 再查。 */
async function checkAccountStatus(acc: backend.CheckAccount): Promise<void> {
  //: 视图归视图宿主(views/viewHost),每次现取 —— 宿主重建之后不攥着一份旧的。
  const views = hostedViews();
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
    contentKind: "video",
    mediaPaths: [],
    body: "",
    title: "",
    tags: [],
    platformOptions: { description: "", shortTitle: "" },
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
    // 复检途中用户点了登录:这台视图已经交给登录流程,刚才的判定看的可能是登录页上的半截现场
    // (线上:视频号的复检在人还停在「微信快捷登录」时回写了 bound)。账号状态归登录轮询管,不回写。
    if (loginAccounts.has(acc.account_id)) {
      plog("recheck abandoned (login took over):", acc.account_id);
      return;
    }
    plog("recheck result:", acc.account_id, loggedIn ? "bound" : "login_required");
    await backend.patchAccount(acc.account_id, {
      binding_status: loggedIn ? "bound" : "login_required",
      last_error: loggedIn ? null : tr("publishErr_sessionExpired"),
    });
    // 从「已登录」变「失效」才通知:后台静默复检没有前台现场,用户不主动看发布台就不知道掉线——
    // 补一条系统通知 + dock 角标。对本就 login_required 的账号不重复弹(只认 bound→失效这一次跳变)。
    if (acc.binding_status === "bound" && !loggedIn) {
      settle(stub, "login_required");
    }
  } catch (error) {
    // 登录接管会中止复检在飞的 goto —— 那是预期的,状态同样归登录轮询管。
    if (loginAccounts.has(acc.account_id)) return;
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
    // 心跳:顺便把手上这些任务报上去续 updated_at —— 不带的话,一条跑过 30 分钟的正常发布
    // 会被后端(包括自己的下一拍 claim)判成"发布器中断"。
    await backend.heartbeat([...running.values()]);
    // 补发布任务到并发上限。认领时排除正在跑的账号(同账号串行);拿到就后台并发跑(不 await)。
    while (running.size < MAX_CONCURRENT) {
      const { task } = await backend.claimTask([...running.keys()]);
      if (stopped || gen !== generation || !task) break;
      plog("claimed:", task.id, task.platform, "account:", task.account_id);
      didWork = true;
      running.set(task.account_id, task.id);
      void runTask(task).catch((error) => {
        // runTask 自身兜底了 report;走到这说明兜底之前就炸了(如 toAdapterTask)——必须留痕。
        plog("runTask crashed before report:", task.id, error instanceof Error ? error : String(error));
        running.delete(task.account_id);
      });
    }
    // 没有更多待发任务、且完全空闲(无发布/复检并发、前台无视图占用)时,后台静默复检一个到期账号。
    if (running.size === 0 && rechecking.size === 0 && !hostedViews()?.visibleAccountId) {
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
  onTaskSettled?: (info: SettleInfo) => void;
  onFrame?: (frame: LiveViewFrame) => void;
}): void {
  if (started) return;
  started = true;
  stopped = false;
  generation += 1; // 新一代:旧代在途的 loop/登录轮询不会复活成重复链
  running.clear();
  onSettled = opts.onTaskSettled ?? null;
  onFrame = opts.onFrame ?? null;
  plog("worker started, generation", generation);
  // 开机先来一轮全量巡检:把所有账号标记为待复检,loop 会快速逐个后台核对登录态。
  void backend.markDue().catch(() => undefined);
  loop(generation);
}

export function stopPublishWorker(): void {
  stopped = true;
  for (const controller of taskControllers.values()) controller.abort();
  taskControllers.clear();
  // 停掉登录轮询定时器:视图即将销毁,别再让它空转触发(最多 10 分钟)。在途的 checkLogin/loop
  // 迭代靠 generation/stopped 自我了断,不会复活成重复链。
  if (loginPollTimer) {
    clearTimeout(loginPollTimer);
    loginPollTimer = null;
  }
  // 本次登录已被停止:清掉接管标记,重启后复检可以正常认领;取消本身不产生新的登录态结论。
  loginAccounts.clear();
  // 视图本身归视图宿主,由主进程在这之后 stopViewHost 销毁。
  started = false;
  onFrame = null;
  mirroring = null;
  running.clear();
  onSettled = null;
}

/**
 * 结束一次登录轮询:停定时器,并清掉登录接管标记。
 *
 * 超时、打开/导航失败时用 `unknown` 收起过渡态,让下一拍复检问出真实状态。
 * 用户取消或执行器停止不是一个「未登录」结论:只收尾,不覆盖账号状态;旧 generation 更不能写新一代。
 */
function endLogin(gen: number, accountId?: string, loggedIn = false, writeUnknown = true): void {
  if (accountId) loginAccounts.delete(accountId);
  if (accountId && !loggedIn && writeUnknown && gen === generation && !stopped) {
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

/** 排查日志:一行一个 JSON(userData/browser-trace.log,超 2MB 轮转一份)。 */
const trace = createTrace({ dir: app.getPath("userData") });

/** 触发某账号登录:亮出其视图、打开登录页,轮询登录态并回写后端(最多 10 分钟)。 */
/**
 * 登录失败时留一份**现场**:哪一步、停在哪个地址、分区的 cookie 种下了哪些、认了几次未登录。
 *
 * 为什么非留不可:视频号那轮(2026-10-22)花了三次尝试才定位,前半程全靠人回忆「之前是好的」。
 * 有这份记录,下一次就能直接回答三件事:①登录协议走完了吗 ②会话 cookie 种下来了吗
 * ③种下来之后平台是不是把这一页判成了未登录 —— 这三件事对应三种完全不同的修法。
 */
async function collectLoginForensics(input: {
  accountId: string;
  platform: string;
  reason: string;
  driver: { url(): string; cookieNames(): Promise<string[]> } | null;
  lastNegativeUrl: string;
  negatives: number;
}): Promise<void> {
  try {
    const url = input.driver?.url() ?? "";
    const cookies = (await input.driver?.cookieNames()) ?? [];
    //: 只留这个平台自己的域,别的域(统计、CDN)是噪音。
    const own = cookies.filter((one) => url && one.includes(new URL(url).hostname.split(".").slice(-2).join(".")));
    const session = own.filter((one) => /(session|token|auth|sid|uin|ticket)/i.test(one)).length;
    trace.event("login-forensics", {
      account: input.accountId,
      platform: input.platform,
      reason: input.reason,
      url: url.slice(0, 200),
      lastNegativeUrl: input.lastNegativeUrl.slice(0, 200),
      negatives: input.negatives,
      cookiesForThisSite: own.length,
      credentialishCookies: session,
      cookieNames: own.slice(0, 20),
    });
    plog(
      "login forensics:",
      input.accountId,
      input.reason,
      `url=${url.slice(0, 120)}`,
      `cookies=${own.length}`,
      `credentialish=${session}`,
    );
  } catch (error) {
    plog("login forensics failed:", input.accountId, String(error).slice(0, 120));
  }
}

export async function openLogin(accountId: string, platform: string): Promise<void> {
  //: 视图归视图宿主(views/viewHost),每次现取 —— 宿主重建之后不攥着一份旧的。
  const views = hostedViews();
  if (!views) return;
  // 该账号正有「真发布任务」在后台跑:登录会切它的视图/抢焦点,拒绝,等任务完成。
  // 注意:后台复检(rechecking)不在此列——复检恰恰是为确认登录态,用户手动登录优先级更高,可抢占。
  if (running.has(accountId)) throw new Error(tr("publishErr_accountBusy"));
  // 前台已被别的账号占(另一个登录 / 待确认现场):拒绝,让用户先处理完前台那个。
  if (views.visibleAccountId && views.visibleAccountId !== accountId)
    throw new Error(tr("publishErr_foregroundBusy"));
  // 登录接管:标记后,在飞的复检(若有)遇到它会放弃回写;并中止该视图在飞的 goto/evaluate,
  // 避免复检的旧 goto 与登录的新 goto 互相 abort 把页面留成空白。
  loginAccounts.add(accountId);
  const gen = generation;
  //: 这一步开始有明确的状态了(见 loginPhase):opening → waiting → verifying → bound / failed(原因)。
  const flow = createLoginFlow({
    onChange: (state) => {
      trace.event("login", { account: accountId, platform, ...state });
      plog("login phase:", accountId, state.phase, state.reason || "", state.detail || "");
    },
  });
  try {
    //: 身份跟着平台走:**建视图之前**先告诉它(UA 随第一次请求发出去,加载完再改对那一页没用)——
    //: 视频号要干净 Chrome UA,X 要如实声明 Electron(见 view-identity.cjs)。
    views.setAccountPlatform?.(accountId, platform);
    await views.configureAccount(accountId, await backend.accountProxy(accountId));
    const driver = views.getDriver(accountId);
    // 亮出视图即占据前台单槽,loop 不再对该账号启动新复检;在飞的旧复检 goto 会被下面
    // 登录 goto 的 loadURL 自然覆盖(ERR_ABORTED),不会与登录页互抢。
    views.show(accountId);
    flow.opened();
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
        contentKind: "video",
      mediaPaths: [],
      body: "",
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
    // 每换一页记一行「在这页上判成未登录」。此前轮询一句日志都不留,TikTok 登完停在信息流、
    // 满 10 分钟都没认出来,事后只能从「超时之后的复检一查就是已登录」倒推。
    let lastNegativeUrl = "";
    let negatives = 0;
    const poll = async () => {
      loginPollTimer = null;
      // stop/换代/视图销毁/超时:收工,不再续排。
      if (stopped || gen !== generation || !hostedViews() || Date.now() > deadline) {
        const why = Date.now() > deadline ? "timeout" : "stopped";
        plog("login poll ended without login:", accountId, why);
        flow.fail(why);
        await collectLoginForensics({
          accountId,
          platform,
          reason: why,
          driver,
          lastNegativeUrl,
          negatives,
        });
        endLogin(gen, accountId, false, why === "timeout");
        return;
      }
      // 用户把这个视图收起来了(返回 / 双击 Esc / 切去别的账号)= 他不打算登了。继续轮询没有意义,
      // 而且 loginAccounts 里挂着它会让复检一直跳过这个账号 —— 状态就永远停在「检测中」。
      if (views.visibleAccountId !== accountId) {
        plog("login poll ended (view dismissed):", accountId);
        flow.fail("dismissed");
        await collectLoginForensics({
          accountId,
          platform,
          reason: "dismissed",
          driver,
          lastNegativeUrl,
          negatives,
        });
        endLogin(gen, accountId, false, false);
        return;
      }
      let ok = false;
      flow.verifying();
      try {
        ok = await trace.span("checkLogin", { account: accountId, platform }, () => adapter.checkLogin());
      } catch (error) {
        /* 页面还没到位:留着错误,别把它当成「没登录」的结论 */
        flow.checkFailed(error);
      }
      // checkLogin 挂起期间可能已 stop/换代:再查一次,别对已属新代的共享状态动手或续排。
      if (stopped || gen !== generation || !hostedViews()) {
        endLogin(gen, accountId, false, false);
        return;
      }
      if (!ok) {
        negatives += 1;
        const here = driver.url();
        if (here !== lastNegativeUrl) plog("login poll: not logged in yet at", here.slice(0, 160));
        lastNegativeUrl = here;
        flow.notYet(here);
      }
      if (ok) {
        plog("login poll: logged in", accountId, def.id);
        flow.bound();
        try {
          await backend.patchAccount(accountId, { binding_status: "bound", last_error: null });
        } catch {
          /* 回写失败下个 ttl 再纠正 */
        }
        // 登上了 = 这个内嵌浏览器的差事办完了,自己收回去。此前它会一直挂在前台,用户得再点一次
        // 「返回 Mosael」才能回来 —— 而他刚做完的事本来就以"回到账号池看到已登录"为终点。
        if (hostedViews()?.visibleAccountId === accountId) views.hide();
        endLogin(gen, accountId, true);
        return;
      }
      loginPollTimer = setTimeout(poll, 5000);
    };
    void poll();
  } catch (error) {
    // 打开/导航阶段就失败:收工,再把错误抛给调用方 —— 但**先把现场留下**。
    await collectLoginForensics({
      accountId,
      platform,
      reason: `error: ${String(error).slice(0, 120)}`,
      driver: hostedViews()?.getDriver(accountId) ?? null,
      lastNegativeUrl: "",
      negatives: 0,
    });
    endLogin(gen, accountId);
    throw error;
  }
}

/**
 * 退出登录:清掉这个账号分区里的 cookie / 本地存储 / 缓存,账号回到「需登录」。
 *
 * 此前没有这个动作 —— 卡片上只有「重新登录」,它会带人去平台登录页,而平台见到一个已登录的
 * 会话往往直接续期、把人弹回首页,于是「点了之后还是已登录」。在平台网页里点退出同样靠不住:
 * 有的平台(B 站)只让当前页面的会话失效,分区里别处的 cookie 还在。清分区是唯一确定的做法。
 */
export async function signOutAccount(accountId: string): Promise<void> {
  //: 视图归视图宿主(views/viewHost),每次现取 —— 宿主重建之后不攥着一份旧的。
  const views = hostedViews();
  if (!views) throw new Error(tr("publishErr_notReady"));
  if (running.has(accountId)) throw new Error(tr("publishErr_accountBusy"));
  // 登录轮询还挂着的话先收掉 —— 否则它下一拍在空分区上问一次,把刚写的状态又改一遍。
  if (loginAccounts.has(accountId)) endLogin(generation, accountId, true);
  await views.clearAccountData(accountId);
  plog("signed out (partition cleared):", accountId);
  await backend.patchAccount(accountId, { binding_status: "login_required", last_error: null });
}

/** 手动打开某账号的平台页面:亮出其视图。若该视图已有页面(如刚「仅准备」好的发布表单——hide
 *  只是移除子视图、webContents 与页面都还在),直接恢复,用户可人工确认/真发;否则导航到创作首页。 */
export async function openPage(accountId: string, platform: string): Promise<void> {
  //: 视图归视图宿主(views/viewHost),每次现取 —— 宿主重建之后不攥着一份旧的。
  const views = hostedViews();
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
  //: 视图归视图宿主(views/viewHost),每次现取 —— 宿主重建之后不攥着一份旧的。
  const views = hostedViews();
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

