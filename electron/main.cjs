const {
  app,
  BrowserWindow,
  Menu,
  Notification,
  dialog,
  ipcMain,
  nativeImage,
  net,
  safeStorage,
  screen,
  session,
  shell,
  systemPreferences,
} = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { loginShellPath } = require("./login-shell-path.cjs");
const { SEALED_NAME, shellToken, unlockMasterKey } = require("./master-key.cjs");
const { createAppUrlCheck, createSenderCheck, guardNavigation } = require("./app-origin.cjs");
const { installPermissionPolicy } = require("./web-permissions.cjs");
const { createBackendSupervisor } = require("./backend-lifecycle.cjs");
const { createStartupSplash, lastLogLine } = require("./startup-splash.cjs");
const { createRendererRecovery } = require("./renderer-recovery.cjs");
const { FILE_NAME: WINDOW_STATE_FILE, placeWindow, readSaved, rememberWindowBounds } = require("./window-bounds.cjs");
const { Readable } = require("node:stream");
const { pipeline } = require("node:stream/promises");
const {
  activateStagedRestore,
  finalizeActivatedRestore,
  writeDiagnosticArchive,
} = require("./data-management.cjs");
const { createRecordingPermissionService } = require("./recording-permissions.cjs");
const { pickPath } = require("./path-picker.cjs");
const { WINDOW_CHROME_HEIGHT, TRAFFIC_LIGHT_POSITION } = require("./window-chrome.cjs");
const { bindFullscreenState } = require("./window-state.cjs");
const {
  IPC,
  parseAuthToken,
  parseBrowserLogin,
  parseComfyNavigation,
  parseComfyWorkbenchCall,
  parseComfyWorkbenchOpen,
  parseBrowserProfile,
  parseCaptureMode,
  parseImageUrls,
  parseLocale,
  parseNewPage,
  parsePageId,
  parsePageOrder,
  parsePagesInset,
  parseCoverPage,
  parseOverlay,
  parseFloatShow,
  parseFloatHide,
  parseToastsShow,
  parsePanelId,
  parsePanelLayout,
  parsePanelMuted,
  parsePickPath,
  parsePublishTarget,
  parseReadMode,
  parseRegionSelection,
  parseRestoreStage,
  parseSaveDownload,
  parseSystemStatus,
  parseTaskNotice,
  parseTitleOverlay,
  parseToolsInset,
  parseUrlRequest,
} = require("./ipc-contract.cjs");
const i18n = require("./i18n.cjs");
const { t } = i18n;

// 应用名。开发态跑的是未打包的 Electron.app,菜单栏首项 / Dock 名默认显示 "Electron"。
// macOS dev 的菜单/Dock 名读 Electron.app 的 CFBundleName,由 electron/brand-dev.cjs 在启动前补丁;
// 这里的 setName 影响 app.getName()/部分弹窗,setAppUserModelId 影响 Windows 任务栏归组。
// 打包版统一由 electron-builder 的 productName 决定。必须在 app ready 前调用。
app.setName("Mosael");
app.setAppUserModelId("dev.mosael.app");

// 发布内嵌浏览器拟真:引擎层去掉自动化标记(navigator.webdriver 等),让平台风控不把用户
// 授权的自动化发布误判为爬虫。页面级补丁见 electron/account-view-preload.cjs。
app.commandLine.appendSwitch("disable-blink-features", "AutomationControlled");
// 浏览器自动化的会话视图挂在主窗口里。Chromium 在 macOS 上把被别的窗口挡住、或不在当前桌面的窗口当成隐藏:
// 不再出帧,scroll 事件和 IntersectionObserver 都停,滚动加载的列表 / 评论区就不往下加载了 —— 而工作流正是让人
// 切走去干别的时候在跑(实测:B 站评论区读页面那一路从 33 条一级评论掉到 3 条)。只关这一条,最小化照旧按隐藏。
app.commandLine.appendSwitch("disable-backgrounding-occluded-windows");
// Windows / Linux 的滚动条默认是占布局宽度的「经典」条;Chromium 的 OverlayScrollbars 让它们在
// 这些平台上也悬浮在内容上(macOS 的默认行为)。开着它,界面的悬停显形滚动条在非 Mac 上
// 才不会把内容挤窄再弹回(0 → 6px 的宽度跳变)。
if (process.platform !== "darwin") app.commandLine.appendSwitch("enable-features", "OverlayScrollbars");

const BACKEND_PORT = Number(process.env.MOSAEL_BACKEND_PORT || 8800);
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const isDev = !app.isPackaged;
// 应用自己的页面在哪:开发时是 Vite,打包后是 dist 里的文件。主窗口只许停在这里、IPC 只收这里发来的、壳令牌只加在
// 这里发出的请求上(见 app-origin.cjs)。
const FRONTEND_URL = process.env.MOSAEL_FRONTEND_URL || "http://127.0.0.1:5173";
const FRONTEND_DIST = path.join(__dirname, "..", "frontend", "dist");
const isAppUrl = createAppUrlCheck({ isPackaged: !isDev, frontendUrl: FRONTEND_URL, distDir: FRONTEND_DIST });
// 打包产物冒烟由 CI 显式开启。结果写文件而不是只看退出码：壳、冻结后端、renderer
// 任一层提前退出都可能同样得到 code 0，结构化结果才说得清实际走到了哪一步。
const smokeResultPath = process.env.MOSAEL_SMOKE_TEST_RESULT || "";
const isSmokeTest = Boolean(smokeResultPath);
const recordingPermissions = createRecordingPermissionService({
  platform: process.platform,
  shell,
  systemPreferences,
});

// 冒烟必须能和开发版/已安装版并行跑。Electron 的单实例锁跟 userData 目录绑定；如果继续
// 使用真实用户目录，本机开着 Mosael 时打包产物会在 requestSingleInstanceLock()
// 这里提前退出，CI/本地测试都没有真正穿过后端启动与数据库升级这条 Seam。
// 结果文件本来就在 mkdtemp 目录中，顺手把 userData 也隔离到同一个可回收目录。
if (isSmokeTest) {
  app.setPath("userData", path.join(path.dirname(smokeResultPath), "electron-user-data"));
}

const electronLogDir = path.join(app.getPath("userData"), "logs");
const mainLogPath = path.join(electronLogDir, "main.log");
const configuredDataDir = process.env.MOSAEL_DATA_DIR
  ? path.resolve(process.env.MOSAEL_DATA_DIR)
  : path.join(os.homedir(), ".mosael");

function rotateLogIfLarge(file, maxBytes = 5 * 1024 * 1024) {
  try {
    if (fs.statSync(file).size <= maxBytes) return;
    fs.rmSync(`${file}.1`, { force: true });
    fs.renameSync(file, `${file}.1`);
  } catch (error) {
    if (error && error.code !== "ENOENT") throw error;
  }
}

function appendMainLog(kind, detail) {
  try {
    fs.mkdirSync(electronLogDir, { recursive: true });
    rotateLogIfLarge(mainLogPath);
    const message = detail instanceof Error ? detail.stack || detail.message : String(detail ?? "");
    fs.appendFileSync(mainLogPath, `${new Date().toISOString()} ${kind} ${message}\n`, {
      encoding: "utf8",
      mode: 0o600,
    });
  } catch {
    // A full/read-only disk must not turn logging into a second crash.
  }
}

process.on("uncaughtExceptionMonitor", (error) => appendMainLog("uncaught-exception", error));
process.on("unhandledRejection", (reason) => appendMainLog("unhandled-rejection", reason));
app.on("render-process-gone", (_event, webContents, details) => {
  let url = "";
  try {
    url = webContents.getURL();
  } catch {
    // A destroyed WebContents may no longer expose its last URL.
  }
  appendMainLog("render-process-gone", JSON.stringify({ url, ...details }));
});
app.on("child-process-gone", (_event, details) => {
  appendMainLog("child-process-gone", JSON.stringify(details));
});

/** 同一句只记一次:网页可能一遍遍地要同一个权限,别把日志刷满。 */
const loggedOnce = new Set();
function appendMainLogOnce(kind, line) {
  if (loggedOnce.has(`${kind} ${line}`)) return;
  loggedOnce.add(`${kind} ${line}`);
  appendMainLog(kind, line);
}

// 网页权限默认拒绝(见 web-permissions.cjs)。每一个新会话(发布账号、浏览器池档案、RPA / 智能体会话、ComfyUI 工作台的
// 分区)一建出来就装上内嵌网页那一档;默认会话在 ready 之后换成应用那一档。
app.on("session-created", (created) => {
  installPermissionPolicy(created, { isAppUrl: null, log: (line) => appendMainLogOnce("permission", line) });
});

// IPC 只收主窗口自己那个主框架、停在应用地址上时发来的(见 app-origin.cjs)。所有处理器都经这两个注册,
// 不直接用 ipcMain(electron/app-origin.test.ts 盯着)。
const fromAppWindow = createSenderCheck({ isAppUrl, windowOf: (contents) => BrowserWindow.fromWebContents(contents) });
function refusedSender(channel, event) {
  let from = "";
  try {
    from = new URL(event.senderFrame?.url ?? "").origin;
  } catch {
    from = "unknown";
  }
  appendMainLogOnce("ipc-refused", `${channel} from ${from}`);
}
/** 一问一答的处理器。调用方不是应用自己就拒绝(渲染层收到的是一个错误)。 */
function handle(channel, listener) {
  ipcMain.handle(channel, (event, ...args) => {
    if (!fromAppWindow(event)) {
      refusedSender(channel, event);
      throw new Error(`${channel}: refused, the caller is not the Mosael window`);
    }
    return listener(event, ...args);
  });
}
/** 单向的消息。调用方不是应用自己就丢掉。 */
function listen(channel, listener) {
  ipcMain.on(channel, (event, ...args) => {
    if (!fromAppWindow(event)) {
      refusedSender(channel, event);
      return;
    }
    listener(event, ...args);
  });
}

// 冒烟悬挂时,超时那一侧只知道「它没退出」。阶段轨迹**边走边落盘**,于是「卡在哪一站」
// 是一条可读的事实,而不是靠读 356 行 diff 猜 —— Windows 上这一步从 6 秒变成跑不完 90 秒,
// 而 CI 日志里一个字都没有,那次除了「timed out」什么线索都没留下。
const smokeStages = [];
// 结果是**累积**的,不是每次覆盖:阶段打点(`reportSmoke({})`)发生在最终结论之后
// (before-quit / will-quit 都在 app.quit() 之后触发),覆盖式写入会把 backendHealthy
// 那几个字段抹掉,外面读到的就成了「启动不完整」——一个纯粹由诊断代码制造的假失败。
let smokeResult = {};

function reportSmoke(result) {
  if (!smokeResultPath) return;
  smokeResult = { ...smokeResult, ...result };
  try {
    fs.mkdirSync(path.dirname(smokeResultPath), { recursive: true });
    fs.writeFileSync(
      smokeResultPath,
      JSON.stringify(
        { packaged: app.isPackaged, version: app.getVersion(), stages: smokeStages, ...smokeResult },
        null,
        2,
      ),
      "utf8",
    );
  } catch (error) {
    console.error("[smoke] failed to write the result:", error);
  }
}

/** 记一站。带上进程已运行的毫秒数 —— 是「慢」还是「停」要能分得开。 */
function markSmokeStage(stage) {
  if (!isSmokeTest) return;
  smokeStages.push(`${stage}@${Math.round(process.uptime() * 1000)}ms`);
  appendMainLog("smoke-stage", stage);
  reportSmoke({});
}

let quitting = false;

// 发布执行器(老版前身项目移植):esbuild 打成的单文件 bundle,缺失/损坏不挡应用启动,
// 但 publish:* IPC 会抛清晰错误(而不是渲染层遇到 "No handler registered" 直接崩)。
let publish = null;
let publishLoadError = null;
try {
  publish = require("./publish.bundle.cjs");
} catch (e) {
  publishLoadError = e;
  console.warn("[publish] failed to load the publisher (is electron/publish.bundle.cjs built?):", e.message);
}

// 系统能力层(托盘 / 常驻 / 开机自启 / 防睡眠):同样是 esbuild 单文件 bundle,同样不挡启动
// —— 托盘建不出来时应用还能正常用,只是退化成「关窗即退」的老行为。
let system = null;
let systemHandle = null;

// 开发时主进程过期(见 dev-staleness.cjs):哪几份产物变了;能不能替用户重启(由 dev-loop.cjs 拉起时才能)。
const { createStalenessWatcher } = require("./dev-staleness.cjs");
const DEV_RESTART_CODE = Number(process.env.MOSAEL_DEV_RESTART_CODE) || 0;
let staleMainFiles = [];
let staleWatcher = null;
const mainStaleStatus = () => ({ files: staleMainFiles, canRestart: isDev && DEV_RESTART_CODE > 0 });
try {
  system = require("./system.bundle.cjs");
} catch (e) {
  console.warn("[system] failed to load system capabilities (is electron/system.bundle.cjs built?):", e.message);
}

// 单实例:第二次启动不再开一个新应用,而是把参数交给已经在跑的这个并把它唤到前台。
//
// 这不只是为了协议唤起(Windows/Linux 上 mosael:// 与「用 Mosael 打开某文件」都是
// 靠再启动一个进程、把 URL/路径放进 argv 传过来)。没有这把锁,双击两次图标就会有两个实例:
// 两个发布 worker 抢同一批任务、两套内嵌浏览器争同一个登录分区(分区有单会话租约,后到的
// 会被拒),而后端因为端口上已经有个健康的后端就复用,反而看起来"没问题"——很难查。
//
// 必须在 app ready 之前调用。
if (!app.requestSingleInstanceLock()) {
  // 说清楚为什么退出。开发时最容易撞上:上一个实例还开着(或没退干净)就跑 pnpm dev,
  // 新进程拿不到锁直接 quit,concurrently 只看到「electron exited」就把整套 dev 栈 SIGTERM 掉,
  // 现象是「刚起来就全挂了」而没有任何解释。打包版撞上则是双击图标没反应 —— 同样需要说明。
  console.warn("[mosael] another instance is already running; exiting (its window will be brought to the front).");
  app.quit();
} else {
  app.on("second-instance", (_event, argv) => {
    if (system) system.adoptSecondInstance(argv);
    // 还在启动(窗口没建)时不替它建:那时后端还没就绪、IPC 也没注册,窗口建好自然会露面。
    if (BrowserWindow.getAllWindows().length > 0) showWindow();
  });
}

function backendCommand() {
  if (isDev) {
    const backendDir = path.resolve(__dirname, "../backend");
    // 走 `python -m uvicorn` 而不是 .venv/bin/uvicorn:后者是带 shebang 的 console script,
    // 解释器路径在建 venv 时被**写死成绝对路径**——仓库目录一改名,
    // 53 个脚本同时变成 "bad interpreter",而 .venv/bin/python 是符号链接、照常可用。
    // venv 布局分平台:POSIX 是 .venv/bin/python,Windows 是 .venv\Scripts\python.exe。
    // 之前写死了 bin/python,Windows 上开发模式压根拉不起后端。
    const venvPython =
      process.platform === "win32"
        ? path.join(backendDir, ".venv", "Scripts", "python.exe")
        : path.join(backendDir, ".venv", "bin", "python");
    return {
      command: venvPython,
      // 关机时最多等没结束的请求 5 秒,然后照样跑后端的收尾(停本机服务等)—— 数字和 backend/app/core/lifeline.py 的
      // GRACEFUL_SHUTDOWN_SECONDS 一致(backend/tests/test_shutdown_does_not_wait_forever.py 对着)。
      args: [
        "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(BACKEND_PORT),
        "--timeout-graceful-shutdown", "5",
      ],
      cwd: backendDir,
    };
  }
  const packagedDir = path.join(process.resourcesPath, "backend", "mosael-backend");
  const executable = process.platform === "win32" ? "mosael-backend.exe" : "mosael-backend";
  return { command: path.join(packagedDir, executable), args: [], cwd: packagedDir };
}

/**
 * 给这个应用发往本机后端的请求加上 `X-Mosael-Shell`(见 master-key.cjs 的壳令牌)。只挂本机后端的地址 ——
 * 连远程服务器时那边不认这个头,也不该把它发出去。
 */
//: 每次起后端都重新算(恢复备份之后数据目录换了,主密钥也就换了),监听只挂一次、读这个变量。
let currentShellToken = "";
let shellHeaderInstalled = false;
function installShellHeader(token) {
  currentShellToken = token;
  if (shellHeaderInstalled) return;
  shellHeaderInstalled = true;
  const urls = [`http://127.0.0.1:${BACKEND_PORT}/*`, `http://localhost:${BACKEND_PORT}/*`];
  session.defaultSession.webRequest.onBeforeSendHeaders({ urls }, (details, callback) => {
    // 只加在应用页面发出的请求上:哪个框架发的就看哪个框架的地址(应用里嵌的第三方 iframe 不算)。
    let from = "";
    try {
      from = details.frame?.url || details.webContents?.getURL() || "";
    } catch {
      // 框架已经没了
    }
    if (!isAppUrl(from)) {
      callback({});
      return;
    }
    callback({ requestHeaders: { ...details.requestHeaders, "X-Mosael-Shell": currentShellToken } });
  });
}

/** /api/health 的回应体;连不上、不是 JSON 都回 null。它带着版本和数据目录指纹(见 backend-lifecycle.cjs)。 */
async function probeBackend() {
  try {
    const res = await net.fetch(`${BACKEND_URL}/api/health`, { signal: AbortSignal.timeout(1500) });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * 封存的主密钥解不开时问人:重试 / (mac)打开钥匙串访问再试 / 退出。说清楚为什么不能「先凑合用着」——
 * 另生一把新钥匙,已存的凭据就再也解不开了。
 * @returns {Promise<"retry" | "keychain" | "quit">}
 */
async function askAboutMasterKey() {
  const mac = process.platform === "darwin";
  const buttons = [t("masterKey_retry"), ...(mac ? [t("masterKey_openKeychain")] : []), t("menu_quitApp")];
  const { response } = await dialog.showMessageBox({
    type: "error",
    title: t("masterKey_title"),
    message: t("masterKey_message"),
    detail: t(mac ? "masterKey_detailMac" : "masterKey_detail", { path: path.join(configuredDataDir, SEALED_NAME) }),
    buttons,
    defaultId: 0,
    cancelId: buttons.length - 1,
    noLink: true,
  });
  if (response === 0) return "retry";
  if (mac && response === 1) return "keychain";
  return "quit";
}

/** 打开「钥匙串访问」:macOS 15 起它挪进了 CoreServices,老系统还在「实用工具」里。 */
async function openKeychainAccess() {
  for (const bundle of [
    "/System/Library/CoreServices/Applications/Keychain Access.app",
    "/System/Applications/Utilities/Keychain Access.app",
  ]) {
    if (fs.existsSync(bundle) && !(await shell.openPath(bundle))) return;
  }
}

/**
 * 拉起后端进程(要不要拉、等它就绪、意外退出重拉都是 backendSupervisor 的事)。回 null = 不起了:人在主密钥那个框里选了退出,
 * 这时已经在退出应用。
 */
async function spawnBackendProcess() {
  // 落盘加密的主密钥:系统钥匙串封存,经标准输入交给后端(见 master-key.cjs)。没有可用的钥匙串时后端照旧用数据目录里的
  // secret.key。封存过却解不开就停下来问人,人说退出就不起后端 —— 绝不让后端另生一把新钥匙。**只在打包版这么做**:
  // 开发时常有人对着同一个数据目录手动起 uvicorn,明文文件被收走的话,手动起的那个就起不来了。
  let masterKey = null;
  if (!isDev) {
    const resolved = await unlockMasterKey({
      dataDir: configuredDataDir,
      safeStorage,
      // 冒烟里没有人点按钮:直接按退出算,结果文件里记着后端没起来。
      ask: isSmokeTest ? async () => "quit" : askAboutMasterKey,
      openKeychain: openKeychainAccess,
      log: (error) => appendMainLog("master-key-unavailable", error),
    });
    if (!resolved) {
      app.quit();
      return null;
    }
    // 壳令牌:界面(file://,Origin 为 null)发往本机后端的请求都带上它,后端只放行带着它的 null 来源。
    installShellHeader(shellToken(resolved.key));
    if (resolved.sealed) masterKey = resolved.key;
  }

  const { command, args, cwd } = backendCommand();
  // 打包版后端日志落盘(userData/logs/backend.log);之前 ignore 导致后端问题完全无迹可查。
  let stdio = "inherit";
  if (!isDev) {
    try {
      const logDir = path.join(app.getPath("userData"), "logs");
      fs.mkdirSync(logDir, { recursive: true });
      const backendLogPath = path.join(logDir, "backend.log");
      rotateLogIfLarge(backendLogPath, 10 * 1024 * 1024);
      const fd = fs.openSync(backendLogPath, "a", 0o600);
      stdio = ["ignore", fd, fd];
    } catch (error) {
      //: backend.log 打不开,后端的全部输出就没有任何地方可看了 —— 至少 main.log 里要有一笔。
      stdio = "ignore";
      appendMainLog("backend-log-unwritable", error);
    }
  }
  // LOCAL_DESKTOP 标记后端「和用户文件在同一台机器上」,门控 /api/assets/import-local
  // (拖到应用图标上的文件由后端直接按路径读)。团队服务器不会有这个标记,那个接口在那边 404。
  const backendEnv = {
    ...process.env,
    MOSAEL_BACKEND_PORT: String(BACKEND_PORT),
    // Always pass an absolute path. Python and Electron otherwise resolve a relative
    // MOSAEL_DATA_DIR from different working directories, which would make restore
    // staging target one directory while the shell swaps another.
    MOSAEL_DATA_DIR: configuredDataDir,
    MOSAEL_LOCAL_DESKTOP: "1",
    // 应用版本的唯一真相在 package.json,壳读得到而后端读不到(打包版是 PyInstaller
    // 冻结二进制,连仓库都不在)。所以由壳传进去 —— 后端自己维护第二个版本号必然漂移,
    // 智能体能力面板此前就一直显示 pyproject 里那个从未更新过的 0.1.0。
    MOSAEL_APP_VERSION: app.getVersion(),
    // 壳被强杀时不会执行任何清理;后端盯着这个 pid,壳没了就自己收尾退出(backend app/core/lifeline.py)。
    MOSAEL_PARENT_PID: String(process.pid),
  };
  if (!isDev) {
    // 打包版从 Finder / Dock 启动时 PATH 是 launchd 的最小集,插件找不到 node / uvx(见 login-shell-path)。
    // 开发时是从终端起的,PATH 本来就对,不必多起一个 shell。
    backendEnv.PATH = await shellPath();
    // 打包版:pi sidecar 随资源分发,用 Electron 二进制(当 node)拉起
    backendEnv.MOSAEL_PI_SIDECAR = path.join(process.resourcesPath, "agent-sidecar", "sidecar.cjs");
    backendEnv.MOSAEL_AGENT_BIN_NODE = process.execPath;
    // 声音克隆的运行环境由后端在用户数据目录里自建(见 domain/tts_config.MANAGED_TTS_VENV),
    // 但打包版后端是 PyInstaller 冻结二进制,建不了 venv——所以把随包分发的独立解释器指给它。
    // 只带解释器(~40MB),torch 等数 GB 依赖点「下载」时才装,不进安装包。
    const ttsPython = path.join(
      process.resourcesPath,
      "python",
      process.platform === "win32" ? "python.exe" : path.join("bin", "python3"),
    );
    if (fs.existsSync(ttsPython)) backendEnv.MOSAEL_TTS_BASE_PYTHON = ttsPython;
  }
  if (masterKey) {
    backendEnv.MOSAEL_SECRET_KEY_STDIN = "1";
    stdio = stdio === "inherit" ? ["pipe", "inherit", "inherit"] : stdio === "ignore" ? ["pipe", "ignore", "ignore"] : ["pipe", stdio[1], stdio[2]];
  }
  const spawnedBackend = spawn(command, args, {
    cwd,
    env: backendEnv,
    stdio,
    // Windows:后端是 PyInstaller 的 console 子系统 exe(spec 里 console=True),被 spawn 时
    // 系统会**另开一个真实的控制台窗口**,而且它活到后端退出为止——用户看到的就是"启动 App
    // 跟着弹一个黑框终端且关不掉"。windowsHide 走 CREATE_NO_WINDOW 把它压掉。
    //
    // 不改成 --noconsole 打包:那样 exe 会变成 windowed 子系统,手动双击跑它排查问题时也
    // 看不到任何输出,且 Python 往失效的 stdout 句柄写会抛异常。保持它是普通控制台程序、
    // 只在我们 spawn 时隐藏窗口(输出照常进 userData/logs/backend.log)。
    // 非 Windows 上该字段被忽略。
    windowsHide: true,
  });
  if (masterKey && spawnedBackend.stdin) spawnedBackend.stdin.end(`${masterKey}\n`);
  return spawnedBackend;
}

/** 登录 shell 里的 PATH(见 login-shell-path.cjs):起一次 shell 要几百毫秒到几秒,只取一次、后端重启时接着用。 */
let shellPathOnce = null;
const shellPath = () => (shellPathOnce ??= loginShellPath());

/** 两处日志:壳和后端的输出(userData/logs:main.log、backend.log)、后端自己写的(数据目录的 logs)。 */
const logPlaces = () => ({ logs: electronLogDir, dataLogs: path.join(configuredDataDir, "logs") });

/**
 * Windows 上退出时请后端自己收尾(见 backend-lifecycle 的 shutdown):Node 在那边的 kill 就是强杀。只认壳令牌 ——
 * 开发时没有壳令牌,回 false,照旧强杀。
 */
async function requestBackendShutdown() {
  if (!currentShellToken) return false;
  try {
    const res = await net.fetch(`${BACKEND_URL}/api/health/shutdown`, {
      method: "POST",
      headers: { "X-Mosael-Shell": currentShellToken },
      signal: AbortSignal.timeout(2000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** 连崩认输:说清楚、给「再试一次」。不用模态的 showErrorBox —— 那会把整个主进程卡在一个框上。 */
async function askAfterBackendGaveUp(lastExit) {
  const { response } = await dialog.showMessageBox({
    type: "error",
    title: t("backend_stoppedTitle"),
    message: t("backend_stoppedTitle"),
    detail: t("backend_stoppedBody", { code: String(lastExit ?? "?"), ...logPlaces() }),
    buttons: [t("backend_retry"), t("menu_quitApp")],
    defaultId: 0,
    cancelId: 1,
    noLink: true,
  });
  if (response === 0) {
    const result = await backendSupervisor.retry();
    appendMainLog("backend-retry", result.status);
    return;
  }
  app.quit();
}

//: 内置后端的一生:起、等就绪、意外退出退避重启、认输后再试、退出时收尾(规则见 backend-lifecycle.cjs)。
const backendSupervisor = createBackendSupervisor({
  probe: probeBackend,
  spawn: spawnBackendProcess,
  expected: { version: app.getVersion(), dataDir: configuredDataDir, strict: !isDev },
  requestShutdown: requestBackendShutdown,
  onGiveUp: (lastExit) => void askAfterBackendGaveUp(lastExit),
  log: appendMainLog,
});

/**
 * 启动时起后端。等得久了(首次打开、升级迁移)亮「正在启动」小窗,显示等了多久、后端日志的最后一句;人在小窗里点退出就退出。
 * 冒烟里没人看着:不亮小窗,等够两分钟算没起来,结果文件里记一笔。
 */
async function startBackendOnLaunch() {
  const SPLASH_AFTER_MS = 4_000;
  const SLOW_AFTER_MS = 180_000;
  const backendLog = path.join(electronLogDir, "backend.log");
  const splash = createStartupSplash({
    BrowserWindow,
    strings: { title: t("startup_title"), body: t("startup_body"), quit: t("menu_quitApp"), lang: i18n.getLocale() },
    onQuit: () => app.quit(),
  });
  try {
    return await backendSupervisor.start({
      initial: true,
      deadlineMs: isSmokeTest ? 120_000 : undefined,
      onWaiting: (elapsedMs) => {
        if (isSmokeTest || quitting || elapsedMs < SPLASH_AFTER_MS) return;
        splash.show();
        splash.update({
          elapsed: t("startup_elapsed", { seconds: Math.round(elapsedMs / 1000) }),
          log: isDev ? "" : lastLogLine(backendLog),
          ...(elapsedMs >= SLOW_AFTER_MS ? { body: t("startup_slowBody", logPlaces()) } : {}),
        });
      },
    });
  } finally {
    splash.close();
  }
}

// ---------------- 应用更新(检查-提示式) ----------------
// 更新仍使用「检查 + 提示 + 打开发布页」:GitHub Releases 比对版本号。
// Developer ID 签名不改变更新安装方式；静默安装需独立的更新器实现和验证。
// 必须是 GitHub 上的规范仓库名(大小写一致)。写错大小写 API 会返回 301,虽然 fetch
// 默认跟随重定向仍能work,但更新检查的失败是静默的——一旦重定向失效就再没人发现。
const UPDATE_REPO = "Alndaly/Mosael";

function compareVersions(a, b) {
  const parse = (value) => String(value).replace(/^v/i, "").split(".").map((part) => parseInt(part, 10) || 0);
  const [pa, pb] = [parse(a), parse(b)];
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff) return diff > 0 ? 1 : -1;
  }
  return 0;
}

async function checkForUpdates() {
  const res = await net.fetch(`https://api.github.com/repos/${UPDATE_REPO}/releases/latest`, {
    headers: { Accept: "application/vnd.github+json", "User-Agent": "mosael-updater" },
  });
  if (!res.ok) throw new Error(`GitHub ${res.status}`);
  const release = await res.json();
  const latest = String(release.tag_name || "").replace(/^v/i, "");
  // 解析不出版本号就报错,不要静默当成「已是最新」。原来是 `Boolean(latest) && ...`,
  // 于是响应形状一变(字段缺失、返回了别的 JSON),用户看到的是一句让人安心的
  // 「已是最新版本」——而实际上这次检查根本没成功。宁可说失败,也不要给假的安心。
  if (!latest) throw new Error(t("update_noTag"));
  const current = app.getVersion();
  return {
    current,
    latest,
    hasUpdate: compareVersions(latest, current) > 0,
    url: release.html_url || `https://github.com/${UPDATE_REPO}/releases`,
  };
}

/**
 * 界面语言:主进程(菜单、托盘、对话框、通知)和两个 bundle(发布器的失败原因、托盘)一起切。
 *
 * 语言由渲染层报上来(preload 盯着 `<html lang>`,见 preload.cjs);报上来之前用系统语言垫着。
 * bundle 各自打包了一份 i18n.cjs,状态不和这里共享,所以要逐个转告(见 i18n.cjs 开头)。
 */
function applyLocale(raw) {
  const locale = i18n.setLocale(raw);
  publish?.setLocale?.(locale);
  system?.setLocale?.(locale);
  return locale;
}

/**
 * 缩放主窗口的界面:`"reset"` 回到 100%,数字是缩放级别的增减(和 Chromium 的 ⌘+ / ⌘- 一样每步 0.5 级)。
 * 改完让内嵌视图按新的缩放重新摆。
 */
function zoomWindow(change) {
  const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0];
  if (!win || win.isDestroyed()) return;
  const contents = win.webContents;
  contents.setZoomLevel(change === "reset" ? 0 : contents.getZoomLevel() + change);
  publish?.hostZoomChanged?.();
}

/** 应用菜单(按界面语言出标签 + 标准 role 行为/快捷键)。mac 是全局顶部菜单栏;
 *  Win/Linux 菜单栏默认隐藏(无边框自绘标题),Alt 唤起,快捷键始终生效。
 *  界面语言变了会整个重建一遍(见 applyLocale)。 */
function buildAppMenu() {
  const isMac = process.platform === "darwin";
  const about = {
    label: t("menu_about"),
    click: () =>
      dialog.showMessageBox({
        type: "info",
        title: "Mosael",
        message: "Mosael",
        detail: t("menu_aboutVersion", { version: app.getVersion() }),
        buttons: [t("common_ok")],
      }),
  };
  const template = [
    ...(isMac
      ? [
          {
            label: "Mosael",
            submenu: [
              about,
              { type: "separator" },
              { role: "services", label: t("menu_services") },
              { type: "separator" },
              { role: "hide", label: t("menu_hide") },
              { role: "hideOthers", label: t("menu_hideOthers") },
              { role: "unhide", label: t("menu_unhide") },
              { type: "separator" },
              { role: "quit", label: t("menu_quitApp") },
            ],
          },
        ]
      : []),
    {
      label: t("menu_file"),
      submenu: [isMac ? { role: "close", label: t("menu_closeWindow") } : { role: "quit", label: t("menu_quit") }],
    },
    {
      label: t("menu_edit"),
      submenu: [
        { role: "undo", label: t("menu_undo") },
        { role: "redo", label: t("menu_redo") },
        { type: "separator" },
        { role: "cut", label: t("menu_cut") },
        { role: "copy", label: t("menu_copy") },
        { role: "paste", label: t("menu_paste") },
        { role: "selectAll", label: t("menu_selectAll") },
      ],
    },
    {
      label: t("menu_view"),
      submenu: [
        // **⌘R 刷的是「你正在看的那一页」。** role:"reload" 永远刷主窗口,而内嵌浏览器占着前台时
        // 用户看到的是平台页面 —— 刷掉主窗口既不符合预期,还会把渲染层重置成"没有内嵌视图"的
        // 初始状态(顶部工具条随之消失,而原生视图还盖在窗口上)。
        {
          label: t("menu_reload"),
          accelerator: "CmdOrCtrl+R",
          click: () => {
            const win = BrowserWindow.getFocusedWindow();
            // 界面自己崩了的时候,内嵌网页亮着也先救界面(否则 Mosael 那一圈一直是死的)。
            if (publish?.embeddedViewVisible?.() && !win?.webContents.isCrashed()) publish.viewReload();
            else win?.webContents.reload();
          },
        },
        {
          label: t("menu_forceReload"),
          accelerator: "Shift+CmdOrCtrl+R",
          click: () => {
            const win = BrowserWindow.getFocusedWindow();
            if (publish?.embeddedViewVisible?.() && !win?.webContents.isCrashed()) publish.viewReload();
            else win?.webContents.reloadIgnoringCache();
          },
        },
        { role: "toggleDevTools", label: t("menu_devTools") },
        { type: "separator" },
        // 不用 resetZoom / zoomIn / zoomOut 这几个 role:缩放的是 Mosael 的界面,而内嵌网页、工作台画布这些原生视图要跟着
        // 重新摆(它们的位置按界面的 CSS 像素算,见 accountViews 的 hostZoom),role 改完缩放不告诉任何人。
        { label: t("menu_resetZoom"), accelerator: "CmdOrCtrl+0", click: () => zoomWindow("reset") },
        { label: t("menu_zoomIn"), accelerator: "CmdOrCtrl+Plus", click: () => zoomWindow(0.5) },
        { label: t("menu_zoomOut"), accelerator: "CmdOrCtrl+-", click: () => zoomWindow(-0.5) },
        { type: "separator" },
        { role: "togglefullscreen", label: t("menu_fullscreen") },
      ],
    },
    {
      label: t("menu_window"),
      submenu: [
        { role: "minimize", label: t("menu_minimize") },
        ...(isMac
          ? [{ role: "zoom", label: t("menu_zoom") }, { type: "separator" }, { role: "front", label: t("menu_front") }]
          : [{ role: "close", label: t("menu_close") }]),
      ],
    },
    ...(isMac ? [] : [{ label: t("menu_help"), submenu: [about] }]),
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

/** 界面一载入就崩、连崩了几次:不再自己重来,问人要不要再载一次。 */
async function askAfterRendererCrashes(win, details) {
  if (win.isDestroyed()) return;
  const { response } = await dialog.showMessageBox(win, {
    type: "error",
    title: t("renderer_crashedTitle"),
    message: t("renderer_crashedTitle"),
    detail: t("renderer_crashedBody", { reason: String(details.reason), ...logPlaces() }),
    buttons: [t("renderer_reload"), t("menu_quitApp")],
    defaultId: 0,
    cancelId: 1,
    noLink: true,
  });
  if (response === 0 && !win.isDestroyed()) win.webContents.reload();
  else if (response === 1) app.quit();
}

/** 把主窗口叫到前台:不在就建一个,最小化了就还原。托盘、Dock(activate)、第二次启动、深链都走这一个。 */
function showWindow() {
  let win = BrowserWindow.getAllWindows()[0];
  if (!win || win.isDestroyed()) {
    createWindow();
    win = BrowserWindow.getAllWindows()[0];
  }
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

let mainWindowCreated = false;

function createWindow() {
  mainWindowCreated = true;
  const isMac = process.platform === "darwin";
  // 上次在哪、多大就照原样打开(对得上此刻的显示器才用,见 window-bounds.cjs)。
  const windowStateFile = path.join(app.getPath("userData"), WINDOW_STATE_FILE);
  const primary = screen.getPrimaryDisplay();
  const placement = placeWindow(
    readSaved(windowStateFile),
    [primary, ...screen.getAllDisplays().filter((display) => display.id !== primary.id)],
    { width: 1440, height: 900, minWidth: 980, minHeight: 640 },
  );
  const win = new BrowserWindow({
    show: !isSmokeTest,
    ...placement.bounds,
    minWidth: 980,
    minHeight: 640,
    title: "Mosael",
    backgroundColor: "#f0f1f3",
    // 无边框标题栏(参考前身项目):mac 红绿灯与顶栏操作垂直居中,
    // Win/Linux 用 titleBarOverlay 把窗口控件叠在右上(高度与应用顶栏共用 56px)。
    titleBarStyle: "hidden",
    ...(isMac
      ? { trafficLightPosition: TRAFFIC_LIGHT_POSITION }
      : { titleBarOverlay: { color: "#ffffff", symbolColor: "#656c78", height: WINDOW_CHROME_HEIGHT } }),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      // Electron 20+ sandboxes preload scripts by default. A sandboxed preload may only require
      // Electron and a tiny built-in allowlist, so our shared IPC contract must be bundled into
      // this single file rather than loaded through a relative require at runtime.
      preload: path.join(__dirname, "preload.bundle.cjs"),
    },
  });
  if (placement.maximized && !isSmokeTest) win.maximize();
  rememberWindowBounds(win, windowStateFile);
  // 无边框自绘标题:菜单栏默认隐藏,Win/Linux 下按 Alt 唤起(快捷键始终有效)。
  win.setMenuBarVisibility(false);
  win.autoHideMenuBar = true;
  // 屏幕录制:getDisplayMedia 在 Electron 里需要主进程给出捕获源。优先用系统原生选择器
  // (mac 15+/Win 支持);否则回退到 desktopCapturer 授予主屏。macOS 首次会弹「屏幕录制」系统授权。
  const { desktopCapturer } = require("electron");
  const { createDisplayMediaGrant } = require("./display-media.cjs");
  win.webContents.session.setDisplayMediaRequestHandler(
    (request, callback) => {
      desktopCapturer
        .getSources({ types: ["screen", "window"] })
        .then((sources) =>
          callback(
            sources[0]
              ? createDisplayMediaGrant(sources[0], { audioRequested: request.audioRequested })
              : {},
          ),
        )
        .catch(() => callback({}));
    },
    { useSystemPicker: true },
  );
  // 全屏时系统窗口控件(mac 红绿灯 / Win 标题栏三键)消失,顶栏为它们预留的边距要撤掉。
  bindFullscreenState(win, IPC.event.fullscreen);
  // 视图状态是**推的**,渲染层没法主动问。它一旦重新加载(⌘R、HMR、崩溃恢复),PublishViewBar
  // 就回到初始的 visible:false —— 而原生视图还盖在窗口上,表现为「内嵌浏览器还在,顶部工具条没了」。
  // 和上面的全屏状态同一个道理,补播一次。
  win.webContents.on("did-finish-load", () => {
    if (!win.isDestroyed()) publish?.republishViewState?.();
  });
  // 工作台那一页(顶栏、右边那一列)是渲染层自己的状态,换一份文档就没了、认领不了它的 ComfyUI 视图:换文档的那一刻
  // 收起它(普通网页留着,上面那一帧补播把顶栏画回来)。见 publishWorker.releaseWorkbenchView。
  win.webContents.on("did-start-navigation", (details) => {
    if (details.isMainFrame && !details.isSameDocument) publish?.releaseWorkbenchView?.();
  });
  // 渲染进程崩了(内存撑爆、GPU 重置):不再留一块灰窗,自动重新载入;一分钟里连崩三次就停下来问人(见 renderer-recovery.cjs)。
  const recover = createRendererRecovery({
    reload: () => {
      if (!win.isDestroyed()) win.webContents.reload();
    },
    giveUp: (details) => void askAfterRendererCrashes(win, details),
    log: (line) => appendMainLog("renderer-recovery", line),
  });
  win.webContents.on("render-process-gone", (_event, details) => {
    publish?.releaseWorkbenchView?.();
    recover(details);
  });
  // 外链(如供应商控制台"获取密钥")走系统浏览器,不在应用内开无控制的新窗口。
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  // 主框架只许停在应用自己的地址上(见 app-origin.cjs):落到别处的页面会拿到 preload 的全部桥。拦下的 http(s) 和上面一样交给
  // 系统浏览器;file:、自定义协议什么都不做。(拖进窗口的文件本来就不导航:Electron 的 navigateOnDragDrop 默认为假。)
  guardNavigation(win.webContents, {
    isAppUrl,
    openExternal: (url) => void shell.openExternal(url),
    log: (line) => appendMainLog("navigation", line),
  });
  markSmokeStage("window-created");
  if (isSmokeTest) {
    win.webContents.once("did-finish-load", async () => {
      // `did-finish-load` does not mean the preload succeeded: Electron logs a preload exception
      // and still finishes the renderer. Verify the public bridge so packaged smoke tests cross
      // the actual sandbox boundary that window chrome and every privileged desktop feature use.
      markSmokeStage("did-finish-load");
      let desktopBridgeReady = false;
      let platformAuthenticatorAvailable = false;
      let bridgeError = null;
      try {
        desktopBridgeReady = await win.webContents.executeJavaScript(
          `typeof window.mosaelDesktop === "object" && ` +
            `window.mosaelDesktop.platform === ${JSON.stringify(process.platform)}`,
        );
        platformAuthenticatorAvailable = await win.webContents.executeJavaScript(
          `typeof PublicKeyCredential !== "undefined" && PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()`,
        );
      } catch (error) {
        // 这个 handler 是 async 的:rejection 此前没人接,于是既不写结果也不退出,外面
        // 只看到一条 90 秒超时。失败也要说话。
        bridgeError = error instanceof Error ? error.message : String(error);
      }
      markSmokeStage("bridge-checked");
      reportSmoke({
        backendHealthy: true,
        rendererLoaded: true,
        desktopBridgeReady,
        platformAuthenticatorAvailable,
        ...(bridgeError ? { bridgeError } : {}),
      });
      markSmokeStage("quit-requested");
      if (desktopBridgeReady) app.quit();
      else app.exit(1);
    });
    win.webContents.once("did-fail-load", (_event, code, description) => {
      reportSmoke({ backendHealthy: true, rendererLoaded: false, error: `${code}: ${description}` });
      app.exit(1);
    });
  }
  if (isDev) {
    win.loadURL(FRONTEND_URL);
  } else {
    win.loadFile(path.join(FRONTEND_DIST, "index.html"));
  }

  // 启动发布执行器:后端是任务事实源,这里驱动每账号一个持久登录的内嵌视图。
  // mac 关窗→重新激活会重建窗口:先 stop 再 start,把视图挂到新窗口上。
  if (publish) {
    try {
      publish.stopPublishWorker();
      publish.startPublishWorker({
        window: win,
        onViewChanged: (state) => {
          if (!win.isDestroyed()) win.webContents.send(IPC.event.publishView, state);
        },
        // 悬浮卡片几何:原生 WebContentsView 画不了圆角/阴影,所以渲染层照这些矩形在视图**下方**
        // 画卡片外壳(子视图永远盖在宿主页面之上,于是卡片的圆角边框会在视图四周露出来)。
        onPanels: (cards) => {
          if (!win.isDestroyed()) win.webContents.send(IPC.event.publishPanels, cards);
        },
        // 内嵌浏览器里点的下载(不弹系统保存框):进度与结果交给渲染层,由它存进素材库、在顶栏说一句。
        onDownload: (notice) => {
          if (!win.isDestroyed()) win.webContents.send(IPC.event.pageToolsDownload, notice);
        },
        // 提示条那一块浮层视图上的指针(ADR 0051):渲染层据此点真的那条提示。
        onToastsPointer: (pointer) => {
          if (!win.isDestroyed()) win.webContents.send(IPC.event.toastsPointer, pointer);
        },
        // 网页在前台时按的 ⌘K:键盘交回 Mosael,开命令面板(ADR 0051)。
        onCommandPalette: () => {
          if (win.isDestroyed()) return;
          win.webContents.focus();
          win.webContents.send(IPC.event.commandPalette);
        },
        // ComfyUI 工作台:主进程轮询内嵌画布里的桥看到的(选中、脏标记、能力、事件),规整过才发;null 是会话结束了。
        onWorkbench: (update) => {
          if (!win.isDestroyed()) win.webContents.send(IPC.event.comfyuiWorkbench, update);
        },
        // 发布任务在后台不可见的账号视图里跑,用户否则完全看不到它在做什么。走与 RPA 相同的
        // browser:frame 通道和同一个前端面板——「自动化浏览器在干什么」对用户是一件事,不该
        // 因为内部分了两个 worker 就冒出两个窗口。
        onFrame: (frame) => {
          if (!win.isDestroyed()) win.webContents.send(IPC.event.browserFrame, frame);
        },
        // 只报**任务中心看不到的那些状态**。
        //
        // 发布状态会被映射到 job(见 domain/publish/worker._sync_job):success →
        // succeeded,failed/cancelled → failed,其余一律停在 running。而渲染层的 TaskCenter
        // 是按 job 的终态跃迁发通知的 —— 所以这四个成败状态两边都会报,同一件事弹两条系统通知。
        //
        // 反过来,login_required / waiting_manual 这类「需要人介入」的中间态,job 还是 running,
        // TaskCenter 永远看不到,只有这里能报。按这条线切开,两边就没有重叠了。
        onTaskSettled: (info) => {
          const titleKeys = {
            login_required: "notice_loginRequired",
            waiting_manual: "notice_waitingManual",
            permission_required: "notice_permissionRequired",
            blocked: "notice_blocked",
          };
          // success / failed / cancelled 交给 TaskCenter(它按 job 终态发,标签和其它任务一致)。
          if (!titleKeys[info.status]) return;
          const notice = {
            title: t(titleKeys[info.status]),
            body: `${info.accountName} · ${info.title || t("common_untitled")}`,
          };
          // 走系统能力层的统一入口:那里带「窗口有焦点就不发」的规则。发布任务在渲染层的
          // TaskCenter 里也会弹应用内 toast,两边都无条件弹的话,你正看着界面时同一件事会
          // 被告知两遍。系统能力没加载时退回直接弹(总比不提示强)。
          if (system) {
            system.showTaskNotification(notice);
          } else if (Notification.isSupported()) {
            new Notification(notice).show();
          }
        },
      });
    } catch (e) {
      console.warn("[publish] failed to start the publisher:", e.message);
    }
  }

  // 浏览器自动化执行器(RPA / 智能体):与发布并列,独立会话/分区,不碰发布登录。
  // 会话视图与发布账号视图共用同一套内嵌视图与右下角面板(见 accountViews.createSharedViews),
  // 画面是真实渲染的,不再需要截帧推送 —— 所以这里也不再传 onFrame。
  if (publish && publish.startBrowserWorker) {
    try {
      publish.stopBrowserWorker();
      publish.startBrowserWorker();
    } catch (e) {
      console.warn("[browser] failed to start the browser worker:", e.message);
    }
  }

  win.on("closed", () => {
    try {
      publish?.stopPublishWorker();
      publish?.stopBrowserWorker?.();
    } catch {
      /* 窗口已销毁,忽略 */
    }
  });
}

app.whenReady().then(async () => {
  // 应用自己的页面(主窗口、浮层视图)用默认会话:换成应用那一档权限(session-created 先给它装的是内嵌网页那一档)。
  installPermissionPolicy(session.defaultSession, { isAppUrl, log: (line) => appendMainLogOnce("permission", line) });
  // 最先定语言:下面起后端时的小窗、失败时弹的错误框就要用到它。getLocale 要等 ready。
  applyLocale(app.getLocale());
  // 平台认证器要在 ready 之后配。没签名时它自己会跳过(见 webauthn.cjs 里的三个前提)。
  const platformAuthenticatorConfigured = require("./webauthn.cjs").configurePlatformAuthenticator();
  reportSmoke({ platformAuthenticatorConfigured });
  const started = await startBackendOnLaunch();
  if (started.status !== "ready" && started.status !== "reused") {
    reportSmoke({ backendHealthy: false, rendererLoaded: false, error: `backend did not become healthy (${started.status})` });
    if (isSmokeTest) {
      app.exit(1);
      return;
    }
    // 人在主密钥那个框、或者「正在启动」小窗里选了退出:已经在退了,不再补一个「启动失败」。
    if (quitting || started.status === "cancelled") return;
    appendMainLog("backend-start-failed", JSON.stringify(started));
    if (started.status === "portTaken") {
      dialog.showErrorBox(t("backend_portTakenTitle"), t("backend_portTakenBody", { port: BACKEND_PORT, reason: started.reason }));
    } else {
      dialog.showErrorBox(
        t("backend_startFailedTitle"),
        t("backend_startFailedBody", { port: BACKEND_PORT, code: String(started.code ?? "?"), ...logPlaces() }),
      );
    }
    app.quit();
    return;
  }
  markSmokeStage("backend-healthy");
  finalizeActivatedRestore(configuredDataDir)
    .then((cleaned) => cleaned && appendMainLog("restore-finalized", "previous data removed after health check"))
    .catch((error) => appendMainLog("restore-finalize-failed", error));
  // publish:* handler 只注册一次(activate 重建窗口时不能二次注册)。恒注册:执行器加载失败时
  // 也给渲染层抛清晰错误。
  const requirePublish = () => {
    if (publish) return publish;
    throw new Error(
      publishLoadError
        ? t("publisher_loadFailed", { detail: publishLoadError.message })
        : t("publisher_missing"),
    );
  };
  handle(IPC.invoke.publishLogin, (_e, payload) => {
    const { accountId, platform } = parsePublishTarget(payload, IPC.invoke.publishLogin);
    return requirePublish().openLogin(accountId, platform);
  });
  handle(IPC.invoke.publishOpenPage, (_e, payload) => {
    const { accountId, platform } = parsePublishTarget(payload, IPC.invoke.publishOpenPage);
    return requirePublish().openPage(accountId, platform);
  });
  handle(IPC.invoke.publishSignOut, (_e, payload) => {
    const { accountId } = parsePublishTarget(payload, IPC.invoke.publishSignOut);
    return requirePublish().signOutAccount(accountId);
  });
  handle(IPC.invoke.browserClearProfile, (_e, payload) => {
    const { partition } = parseBrowserProfile(payload);
    return requirePublish().clearPoolProfile(partition);
  });
  handle(IPC.invoke.publishInspect, (_e, payload) => {
    const { accountId, platform } = parsePublishTarget(payload, IPC.invoke.publishInspect);
    return requirePublish().inspectAccount(accountId, platform);
  });
  handle(IPC.invoke.publishNavigate, (_e, payload) => {
    const { url } = parseUrlRequest(payload, IPC.invoke.publishNavigate);
    return requirePublish().navigateView(url);
  });
  handle(IPC.invoke.publishBack, () => requirePublish().viewBack());
  handle(IPC.invoke.publishForward, () => requirePublish().viewForward());
  handle(IPC.invoke.publishReload, () => requirePublish().viewReload());
  handle(IPC.invoke.publishHideView, () => requirePublish().hidePublishView());
  // 悬浮面板:渲染层拖动/缩放/关闭。几何由主进程持有(layout() 要用,还要落盘)。
  handle(IPC.invoke.publishPanelLayout, (_e, payload) =>
    requirePublish().setPanelLayout(parsePanelLayout(payload)),
  );
  handle(IPC.invoke.publishClosePanel, (_e, payload) => {
    const { id } = parsePanelId(payload);
    return requirePublish().closePanel(id);
  });
  // 前台会话的页面列表:切换、关闭、拖动重排、新建、让出左侧那一列。
  handle(IPC.invoke.publishSwitchPage, (_e, payload) =>
    requirePublish().switchViewPage(parsePageId(payload, IPC.invoke.publishSwitchPage).id),
  );
  handle(IPC.invoke.publishClosePage, (_e, payload) =>
    requirePublish().closeViewPage(parsePageId(payload, IPC.invoke.publishClosePage).id),
  );
  handle(IPC.invoke.publishReorderPages, (_e, payload) =>
    requirePublish().reorderViewPages(parsePageOrder(payload).ids),
  );
  handle(IPC.invoke.publishNewPage, (_e, payload) => requirePublish().newViewPage(parseNewPage(payload).url));
  handle(IPC.invoke.publishPagesInset, (_e, payload) =>
    requirePublish().setPagesInset(parsePagesInset(payload).left),
  );
  handle(IPC.invoke.publishSnapshotPage, () => requirePublish().snapshotViewPage());
  handle(IPC.invoke.publishCoverPage, (_e, payload) =>
    requirePublish().coverViewPage(parseCoverPage(payload).covered),
  );
  handle(IPC.invoke.publishOverlay, (_e, payload) => requirePublish().overlayViewPage(parseOverlay(payload).up));
  handle(IPC.invoke.publishFocusPage, () => requirePublish().focusViewPage());
  // 内嵌浏览器外壳里的悬停说明:交给浮层视图画在网页上面 / 收起(只收主窗口自己发来的,listen 那一道已经认过)。
  listen(IPC.send.floatShow, (_event, payload) => {
    if (publish) void publish.showFloat(parseFloatShow(payload));
  });
  listen(IPC.send.floatHide, (_event, payload) => {
    if (publish) publish.hideFloat(parseFloatHide(payload).id ?? undefined);
  });
  // 原生视图在前台时右下角的提示条:交给提示条那一块浮层视图画在网页上面 / 收起(ADR 0051)。
  listen(IPC.send.toastsShow, (_event, payload) => {
    if (publish) void publish.showToasts(parseToastsShow(payload));
  });
  listen(IPC.send.toastsHide, () => {
    if (publish) publish.hideToasts();
  });
  handle(IPC.invoke.publishPanelMuted, (_e, payload) => {
    const { id, muted } = parsePanelMuted(payload);
    return requirePublish().setPanelMuted(id, muted);
  });
  // 通用池档案登录:复用发布账号那套 app **内嵌视图**(不弹外部系统窗,体验与发布登录一致)。
  // 安全:只放行 persist:pool-* 分区(发布账号走 publish:login),只放行 http(s)。
  handle(IPC.invoke.browserOpenLogin, async (_e, payload) => {
    try {
      const request = parseBrowserLogin(payload);
      await requirePublish().openPoolLogin(request);
      return { ok: true };
    } catch (err) {
      return { ok: false, error: String(err && err.message ? err.message : err) };
    }
  });
  // 内嵌 ComfyUI 画布的操控方式(触控板 / 鼠标):写死的脚本经前端的设置仓库设好,写回服务器的那一下只在这个分区上拦下。
  // ComfyUI 工作台(ADR 0038 §3):开 = 亮出视图、注入写死的桥、开始轮询(视图收起就停);面板要桥做的事逐项校验后以 JSON
  // 数据嵌进写死的调用脚本。两条都只认按连接 id 拼出来的分区。
  handle(IPC.invoke.comfyuiOpenWorkbench, async (_e, payload) => {
    try {
      const request = parseComfyWorkbenchOpen(payload);
      return { ok: true, outcome: await requirePublish().openComfyWorkbench(request) };
    } catch (err) {
      return { ok: false, error: String(err && err.message ? err.message : err) };
    }
  });
  handle(IPC.invoke.comfyuiWorkbenchCall, async (_e, payload) => {
    try {
      return await requirePublish().comfyWorkbenchCall(parseComfyWorkbenchCall(payload));
    } catch (err) {
      return { ok: false, error: "invalid", message: String(err && err.message ? err.message : err) };
    }
  });
  handle(IPC.invoke.comfyuiNavigation, async (_e, payload) => {
    try {
      const request = parseComfyNavigation(payload);
      return { ok: true, outcome: await requirePublish().setComfyViewNavigation(request) };
    } catch (err) {
      return { ok: false, error: String(err && err.message ? err.message : err) };
    }
  });
  // 浏览器会话顶栏的页面工具:载荷先过契约里的解析器,作用对象由主进程认(前台视图)。
  handle(IPC.invoke.pageToolsCapture, (_e, payload) =>
    requirePublish().capturePage(parseCaptureMode(payload).mode),
  );
  handle(IPC.invoke.pageToolsRegionStart, () => requirePublish().beginRegionCapture());
  handle(IPC.invoke.pageToolsRegionFinish, (_e, payload) =>
    requirePublish().finishRegionCapture(parseRegionSelection(payload).selection),
  );
  handle(IPC.invoke.pageToolsVideos, () => requirePublish().probeVideos());
  handle(IPC.invoke.pageToolsImages, () => requirePublish().listImages());
  handle(IPC.invoke.pageToolsFetchImages, (_e, payload) =>
    requirePublish().fetchImages(parseImageUrls(payload).urls),
  );
  handle(IPC.invoke.pageToolsRead, (_e, payload) => requirePublish().readPage(parseReadMode(payload).mode));
  handle(IPC.invoke.pageToolsInset, (_e, payload) =>
    requirePublish().setToolsInset(parseToolsInset(payload).right),
  );
  handle(IPC.invoke.pageToolsSaveDownload, (_e, payload) =>
    requirePublish().saveDownload(parseSaveDownload(payload)),
  );
  // 开发时主进程过期提示:主进程启动时加载的产物(main.cjs、几个 bundle)变了,而正在跑的还是旧的 —— 渲染层
  // 热更新成了新代码,去调旧主进程里没有的处理器就会失败。给界面一条「重启后生效」,能重启时带按钮。
  // 正式打包的应用不起这个(isDev 为假)。
  handle(IPC.invoke.mainStatus, () => mainStaleStatus());
  handle(IPC.invoke.restartMain, () => {
    if (!DEV_RESTART_CODE) throw new Error(t("devMain_cannotRestart"));
    // 由 dev-loop.cjs 拉起:以「要重启」的退出码退出,它再拉一遍 Electron;vite、后端那几栏不动。
    appendMainLog("dev-restart", `stale=${staleMainFiles.join(",")}`);
    quitting = true;
    systemHandle?.dispose();
    app.exit(DEV_RESTART_CODE);
  });
  if (isDev && !isSmokeTest) {
    staleWatcher = createStalenessWatcher({
      dir: __dirname,
      onChange: (files) => {
        staleMainFiles = files;
        for (const win of BrowserWindow.getAllWindows()) win.webContents.send(IPC.event.mainStale, mainStaleStatus());
      },
    });
  }
  // 更新检查:设置页「检查更新」按钮主动调;打包版启动后再静默查一次,
  // 有新版把信息推给渲染层弹提示。检查失败(离线/私有仓库)不打扰。
  handle(IPC.invoke.checkUpdates, async () => {
    try {
      return await checkForUpdates();
    } catch (error) {
      appendMainLog("update-check-failed", error);
      return { error: error.message };
    }
  });
  handle(IPC.invoke.recordingStatus, (_event, kind) => recordingPermissions.getStatus(kind));
  handle(IPC.invoke.recordingRequest, (_event, kind) => recordingPermissions.request(kind));
  handle(IPC.invoke.recordingOpenSettings, (_event, kind) => recordingPermissions.openSettings(kind));
  // 路径格旁边的「选择…」:挂在发起的那个窗口上(找不到就用前台窗口),交回选中的路径或 null。
  handle(IPC.invoke.pickPath, (event, payload) =>
    pickPath(dialog, BrowserWindow.fromWebContents(event.sender) ?? BrowserWindow.getFocusedWindow(), parsePickPath(payload)),
  );
  handle(IPC.invoke.dataExportDiagnostics, async () => {
    const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const picked = await dialog.showSaveDialog({
      title: t("dialog_exportDiagnostics"),
      defaultPath: path.join(app.getPath("downloads"), `Mosael-diagnostics-${stamp}.zip`),
      filters: [{ name: t("dialog_zipArchive"), extensions: ["zip"] }],
    });
    if (picked.canceled || !picked.filePath) return { status: "cancelled" };
    const secretValues = Object.entries(process.env)
      .filter(([key, value]) => value && /(KEY|TOKEN|PASSWORD|SECRET)/i.test(key))
      .map(([, value]) => value);
    await writeDiagnosticArchive(picked.filePath, {
      appVersion: app.getVersion(),
      platform: process.platform,
      arch: process.arch,
      homeDir: os.homedir(),
      dataDir: configuredDataDir,
      userDataDir: app.getPath("userData"),
      secrets: secretValues,
      logFiles: [
        path.join(electronLogDir, "backend.log"),
        path.join(electronLogDir, "backend.log.1"),
        mainLogPath,
        `${mainLogPath}.1`,
        path.join(configuredDataDir, "logs", "mosael.log"),
      ],
    });
    return { status: "saved", path: picked.filePath };
  });
  handle(IPC.invoke.dataCreateBackup, async (_event, payload) => {
    const { token } = parseAuthToken(payload, IPC.invoke.dataCreateBackup);
    const stamp = new Date().toISOString().slice(0, 10);
    const picked = await dialog.showSaveDialog({
      title: t("dialog_createBackup"),
      defaultPath: path.join(app.getPath("downloads"), `Mosael-${stamp}.mosael-backup`),
      filters: [{ name: t("dialog_backupFile"), extensions: ["mosael-backup"] }],
    });
    if (picked.canceled || !picked.filePath) return { status: "cancelled" };

    const temporaryPath = `${picked.filePath}.${process.pid}.${Date.now()}.partial`;
    try {
      const response = await net.fetch(`${BACKEND_URL}/api/settings/data/backup`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(30 * 60 * 1000),
      });
      if (!response.ok || !response.body) {
        throw new Error(t("backup_requestFailed", { status: response.status }));
      }
      await pipeline(
        Readable.fromWeb(response.body),
        fs.createWriteStream(temporaryPath, { flags: "wx", mode: 0o600 }),
      );
      await fs.promises.rm(picked.filePath, { force: true });
      await fs.promises.rename(temporaryPath, picked.filePath);
      return { status: "saved", path: picked.filePath };
    } catch (error) {
      await fs.promises.rm(temporaryPath, { force: true }).catch(() => {});
      throw error;
    }
  });
  handle(IPC.invoke.dataApplyRestore, async (_event, payload) => {
    const { stageId } = parseRestoreStage(payload);
    let stopped = false;
    try {
      stopped = await backendSupervisor.stopForRestore().catch(() => {
        throw new Error(t("restore_backendStopTimeout"));
      });
      if (!stopped) throw new Error(t("restore_needsManagedBackend"));
      activateStagedRestore(configuredDataDir, stageId);
      appendMainLog("restore-activated", `stage=${stageId}`);
      quitting = true;
      app.relaunch();
      setTimeout(() => app.exit(0), 100);
      return { status: "restarting" };
    } catch (error) {
      // 恢复没成:接着用原来的数据,把后端拉回来。
      if (stopped) await backendSupervisor.resumeAfterFailedRestore().catch(() => undefined);
      throw error;
    }
  });
  // 「暂时无法加载 · 重试」:后端连崩被认输了的话,这一下真的去重拉它(正跑着就什么都不做),等它就绪再回话。
  handle(IPC.invoke.backendRetry, async () => ({ status: (await backendSupervisor.retry()).status }));
  if (app.isPackaged && !isSmokeTest) {
    // 启动 5 秒后查一次,之后每天查一次(常驻托盘的应用可能几周不重启)。同一个新版本只说一次。
    let announced = "";
    const checkAndAnnounce = async () => {
      try {
        const info = await checkForUpdates();
        if (!info.hasUpdate || info.latest === announced) return;
        announced = info.latest;
        appendMainLog("update-available", `${info.current} -> ${info.latest}`);
        for (const win of BrowserWindow.getAllWindows()) win.webContents.send(IPC.event.updateAvailable, info);
      } catch (error) {
        //: 对用户静默(后台检查失败不该弹窗),但对**日志**不静默 —— 代理挂了、限流撞上了,
        //: 这种事只有写出来,下次「怎么很久没提示更新」才查得回来。
        appendMainLog("update-check-failed", error);
      }
    };
    setTimeout(checkAndAnnounce, 5000);
    setInterval(checkAndAnnounce, 24 * 60 * 60 * 1000);
  }

  buildAppMenu();
  // 渲染层的界面语言(首次加载、以及每次在设置里切换)。变了才重建菜单;托盘由系统能力层自己重建。
  listen(IPC.send.locale, (_event, payload) => {
    const before = i18n.getLocale();
    if (applyLocale(parseLocale(payload).locale) !== before) buildAppMenu();
  });
  // 关于面板信息(mac 标准关于弹窗)。
  app.setAboutPanelOptions({ applicationName: "Mosael", applicationVersion: app.getVersion() });
  // Dock 图标:打包版走 .icns;开发态未打包时 Dock 用的是 Electron 默认图标,这里用打进仓库的
  // build/icon.png 覆盖(路径不存在时 createFromPath 返回空图,跳过)。
  if (process.platform === "darwin" && app.dock) {
    const dockIcon = nativeImage.createFromPath(path.join(__dirname, "..", "build", "icon.png"));
    if (!dockIcon.isEmpty()) app.dock.setIcon(dockIcon);
  }
  // Win/Linux:标题栏三键叠层颜色随前端主题(mosaelDesktop.setTitleOverlay)。mac 无叠层。
  listen(IPC.send.titleOverlay, (event, payload) => {
    if (process.platform === "darwin") return;
    const colors = parseTitleOverlay(payload);
    const win = BrowserWindow.fromWebContents(event.sender);
    try {
      win?.setTitleBarOverlay({ color: colors.color, symbolColor: colors.symbolColor, height: WINDOW_CHROME_HEIGHT });
    } catch {
      // 老版本 / 非 overlay 窗口:忽略。
    }
  });

  createWindow();
  // 点 Dock 图标(mac 的 activate):和托盘「打开 Mosael」同一件事。关窗只是藏起来(system/residency),窗口一直在,
  // 只在「一个窗口都没有时才建」的老写法下,藏起来的窗口点 Dock 叫不回来。
  app.on("activate", () => showWindow());

  // 系统能力:窗口建好之后再注册(residency 要挂到窗口的 close 上)。
  if (system) {
    systemHandle = system.registerSystemCapabilities({
      getWindow: () => BrowserWindow.getAllWindows()[0] ?? null,
      showWindow,
      isDev,
      iconPath: path.join(__dirname, "..", "build", "icon.png"),
      trayTemplatePath: path.join(__dirname, "..", "build", "trayTemplate.png"),
      trayLightPath: path.join(__dirname, "..", "build", "tray-light.png"),
      trayDarkPath: path.join(__dirname, "..", "build", "tray-dark.png"),
    });
    // 渲染层把「有几个任务在跑」推上来 —— 托盘文案和防睡眠都吃这一份,系统层不反查后端。
    listen(IPC.send.systemStatus, (_e, payload) => systemHandle?.pushStatus(parseSystemStatus(payload)));
    // 渲染层在任务结束时调用。发不发由主进程判(窗口藏起来时渲染层的 hasFocus 不可靠)。
    listen(IPC.send.systemNotify, (_e, payload) => system.showTaskNotification(parseTaskNotice(payload)));
    // 开发模式返回 null = 「本环境不支持」,设置页据此隐藏开关。不能只是让它失效:
    // dev 下 process.execPath 是 Electron 二进制,写进登录项等于让开发机开机启动一个裸 Electron。
    handle(IPC.invoke.getOpenAtLogin, () => (isDev ? null : system.getOpenAtLogin()));
    handle(IPC.invoke.setOpenAtLogin, (_e, enabled) =>
      isDev ? null : system.setOpenAtLogin(Boolean(enabled)),
    );

    // 自定义 CSS:渲染层要三样东西 —— 内容(启动时读一次,之后靠推送)、路径(设置页显示)、
    // 以及打开/定位这个文件的两个动作。写入始终由用户在自己的编辑器里完成,应用不代写。
    handle(IPC.invoke.customCssRead, () => system.readCustomCss());
    handle(IPC.invoke.customCssPath, () => system.customCssPath());
    handle(IPC.invoke.customCssOpen, () => system.openCustomCss());
    handle(IPC.invoke.customCssReveal, () => system.revealCustomCss());

    // 开机自启拉起时静默驻留托盘,不弹窗口。
    if (system.isHiddenLaunch()) BrowserWindow.getAllWindows()[0]?.hide();
  }
});

// 关窗不退:窗口只是隐藏(见 system/residency),托盘是应用还活着的可见入口。定时任务
// 依赖后端进程活着,而后端是主进程 spawn 的子进程 —— 以前这里 app.quit() 等于「关窗就把
// 定时任务一起关了」。系统能力没加载成功时退回老行为,否则应用会变成关不掉的幽灵进程。
// 主窗口建出来之前关掉的只可能是「正在启动」小窗:那不是「窗口全关了」。
app.on("window-all-closed", () => {
  if (!mainWindowCreated) return;
  if (!system && process.platform !== "darwin") app.quit();
});

let backendShutDown = false;
app.on("before-quit", (event) => {
  if (!quitting) {
    markSmokeStage("before-quit");
    quitting = true;
    systemHandle?.dispose();
  }
  if (backendShutDown) return;
  // Windows:先请后端自己收尾、等它退,再让壳退(壳一退,作业对象就把它强杀了)。见 backend-lifecycle 的 shutdown。
  if (backendSupervisor.needsGracefulShutdown()) {
    event.preventDefault();
    void backendSupervisor.shutdown().finally(() => {
      backendShutDown = true;
      app.quit();
    });
    return;
  }
  backendShutDown = true;
  void backendSupervisor.shutdown();
});

app.on("will-quit", () => {
  markSmokeStage("will-quit");
  staleWatcher?.close();
  backendSupervisor.killNow();
});
process.on("exit", () => backendSupervisor.killNow());
