const { app, BrowserWindow, Menu, Notification, dialog, ipcMain, nativeImage, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

// 应用名。开发态跑的是未打包的 Electron.app,菜单栏首项 / Dock 名默认显示 "Electron"。
// macOS dev 的菜单/Dock 名读 Electron.app 的 CFBundleName,由 electron/brand-dev.cjs 在启动前补丁;
// 这里的 setName 影响 app.getName()/部分弹窗,setAppUserModelId 影响 Windows 任务栏归组。
// 打包版统一由 electron-builder 的 productName 决定。必须在 app ready 前调用。
app.setName("Mosael");
app.setAppUserModelId("dev.mosael.app");

// productName 改名会让 Electron 换一个 userData 目录。第一次启动 Mosael 时把旧目录整体
// 搬过来，浏览器池登录态、窗口状态和 Chromium 存储才能无缝延续。只在新目录尚不存在时做。
function migrateLegacyUserData() {
  const target = app.getPath("userData");
  const legacy = path.join(app.getPath("appData"), "Open Studio");
  if (fs.existsSync(target) || !fs.existsSync(legacy)) return;
  try {
    fs.renameSync(legacy, target);
  } catch {
    fs.cpSync(legacy, target, { recursive: true, errorOnExist: false });
  }
}

// 发布内嵌浏览器拟真:引擎层去掉自动化标记(navigator.webdriver 等),让平台风控不把用户
// 授权的自动化发布误判为爬虫。页面级补丁见 electron/publish/stealth.ts。
app.commandLine.appendSwitch("disable-blink-features", "AutomationControlled");

const BACKEND_PORT = Number(process.env.MOSAEL_BACKEND_PORT || 8800);
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const isDev = !app.isPackaged;
// 打包产物冒烟由 CI 显式开启。结果写文件而不是只看退出码：壳、冻结后端、renderer
// 任一层提前退出都可能同样得到 code 0，结构化结果才说得清实际走到了哪一步。
const smokeResultPath = process.env.MOSAEL_SMOKE_TEST_RESULT || "";
const isSmokeTest = Boolean(smokeResultPath);

if (!isSmokeTest) migrateLegacyUserData();

// 冒烟必须能和开发版/已安装版并行跑。Electron 的单实例锁跟 userData 目录绑定；如果继续
// 使用真实用户目录，本机开着 Mosael 时打包产物会在 requestSingleInstanceLock()
// 这里提前退出，CI/本地测试都没有真正穿过后端启动与数据库升级这条 Seam。
// 结果文件本来就在 mkdtemp 目录中，顺手把 userData 也隔离到同一个可回收目录。
if (isSmokeTest) {
  app.setPath("userData", path.join(path.dirname(smokeResultPath), "electron-user-data"));
}

function reportSmoke(result) {
  if (!smokeResultPath) return;
  try {
    fs.mkdirSync(path.dirname(smokeResultPath), { recursive: true });
    fs.writeFileSync(
      smokeResultPath,
      JSON.stringify({ packaged: app.isPackaged, version: app.getVersion(), ...result }, null, 2),
      "utf8",
    );
  } catch (error) {
    console.error("[smoke] 写结果失败:", error);
  }
}

let backend = null;
let quitting = false;

// 发布执行器(老版前身项目移植):esbuild 打成的单文件 bundle,缺失/损坏不挡应用启动,
// 但 publish:* IPC 会抛清晰错误(而不是渲染层遇到 "No handler registered" 直接崩)。
let publish = null;
let publishLoadError = null;
try {
  publish = require("./publish.bundle.cjs");
} catch (e) {
  publishLoadError = e;
  console.warn("[publish] 执行器加载失败(electron/publish.bundle.cjs 是否已构建?):", e.message);
}

// 系统能力层(托盘 / 常驻 / 开机自启 / 防睡眠):同样是 esbuild 单文件 bundle,同样不挡启动
// —— 托盘建不出来时应用还能正常用,只是退化成「关窗即退」的老行为。
let system = null;
let systemHandle = null;
try {
  system = require("./system.bundle.cjs");
} catch (e) {
  console.warn("[system] 系统能力加载失败(electron/system.bundle.cjs 是否已构建?):", e.message);
}

// 单实例:第二次启动不再开一个新应用,而是把参数交给已经在跑的这个并把它唤到前台。
//
// 这不只是为了协议唤起(Windows/Linux 上 mosael:// 与「用 Mosael 打开某文件」都是
// 靠再启动一个进程、把 URL/路径放进 argv 传过来)。没有这把锁,双击两次图标就会有两个实例:
// 两个发布 worker 抢同一批任务、两套内嵌浏览器争同一个登录分区(分区有单会话租约,后到的
// 会被拒),而后端因为 ensureBackend 见端口健康就复用,反而看起来"没问题"——很难查。
//
// 必须在 app ready 之前调用。
if (!app.requestSingleInstanceLock()) {
  // 说清楚为什么退出。开发时最容易撞上:上一个实例还开着(或没退干净)就跑 pnpm dev,
  // 新进程拿不到锁直接 quit,concurrently 只看到「electron exited」就把整套 dev 栈 SIGTERM 掉,
  // 现象是「刚起来就全挂了」而没有任何解释。打包版撞上则是双击图标没反应 —— 同样需要说明。
  console.warn("[mosael] 已有一个实例在运行,本次启动退出(窗口会被唤到前台)。");
  app.quit();
} else {
  app.on("second-instance", (_event, argv) => {
    if (system) system.adoptSecondInstance(argv);
    const win = BrowserWindow.getAllWindows()[0];
    if (win && !win.isDestroyed()) {
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
    }
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
      args: ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(BACKEND_PORT)],
      cwd: backendDir,
    };
  }
  const packagedDir = path.join(process.resourcesPath, "backend", "mosael-backend");
  const executable = process.platform === "win32" ? "mosael-backend.exe" : "mosael-backend";
  return { command: path.join(packagedDir, executable), args: [], cwd: packagedDir };
}

async function isHealthy() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/health`, { signal: AbortSignal.timeout(1500) });
    if (!res.ok) return false;
    const body = await res.json();
    return body.status === "ok";
  } catch {
    return false;
  }
}

async function waitForBackend(timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isHealthy()) return true;
    if (backend && backend.exitCode !== null) return false;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  return false;
}

async function ensureBackend() {
  // Port already serving a healthy Mosael backend (e.g. dev uvicorn) → reuse it.
  if (await isHealthy()) return true;

  const { command, args, cwd } = backendCommand();
  // 打包版后端日志落盘(userData/logs/backend.log);之前 ignore 导致后端问题完全无迹可查。
  let stdio = "inherit";
  if (!isDev) {
    try {
      const logDir = path.join(app.getPath("userData"), "logs");
      fs.mkdirSync(logDir, { recursive: true });
      const fd = fs.openSync(path.join(logDir, "backend.log"), "a");
      stdio = ["ignore", fd, fd];
    } catch {
      stdio = "ignore";
    }
  }
  // LOCAL_DESKTOP 标记后端「和用户文件在同一台机器上」,门控 /api/assets/import-local
  // (拖到应用图标上的文件由后端直接按路径读)。团队服务器不会有这个标记,那个接口在那边 404。
  const backendEnv = {
    ...process.env,
    MOSAEL_BACKEND_PORT: String(BACKEND_PORT),
    MOSAEL_LOCAL_DESKTOP: "1",
    // 应用版本的唯一真相在 package.json,壳读得到而后端读不到(打包版是 PyInstaller
    // 冻结二进制,连仓库都不在)。所以由壳传进去 —— 后端自己维护第二个版本号必然漂移,
    // 智能体能力面板此前就一直显示 pyproject 里那个从未更新过的 0.1.0。
    MOSAEL_APP_VERSION: app.getVersion(),
  };
  if (!isDev) {
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
  backend = spawn(command, args, {
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
  backend.on("exit", (code) => {
    backend = null;
    if (!quitting && code !== 0 && code !== null) {
      dialog.showErrorBox("Mosael backend stopped", `The local backend exited unexpectedly (code ${code}). Please restart Mosael.`);
    }
  });
  return waitForBackend(30000);
}

function stopBackend() {
  if (backend && !backend.killed) {
    backend.kill("SIGTERM");
    backend = null;
  }
}

// ---------------- 应用更新(检查-提示式) ----------------
// macOS 未签名包装不上 Squirrel 自动安装(签名校验必失败),所以走「检查 + 提示 +
// 打开发布页」的降级路线:GitHub Releases 比对版本号。日后具备 Developer ID 签名
// 时,可在此平滑升级为 electron-updater 的全自动下载安装,渲染层接口不变。
// 必须是 GitHub 上的规范仓库名(大小写一致)。写错大小写 API 会返回 301,虽然 fetch
// 默认跟随重定向仍能work,但更新检查的失败是静默的——一旦重定向失效就再没人发现。
const UPDATE_REPO = "Alndaly/Moseal";

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
  const res = await fetch(`https://api.github.com/repos/${UPDATE_REPO}/releases/latest`, {
    headers: { Accept: "application/vnd.github+json", "User-Agent": "mosael-updater" },
  });
  if (!res.ok) throw new Error(`GitHub ${res.status}`);
  const release = await res.json();
  const latest = String(release.tag_name || "").replace(/^v/i, "");
  // 解析不出版本号就报错,不要静默当成「已是最新」。原来是 `Boolean(latest) && ...`,
  // 于是响应形状一变(字段缺失、返回了别的 JSON),用户看到的是一句让人安心的
  // 「已是最新版本」——而实际上这次检查根本没成功。宁可说失败,也不要给假的安心。
  if (!latest) throw new Error("GitHub 返回里没有 tag_name");
  const current = app.getVersion();
  return {
    current,
    latest,
    hasUpdate: compareVersions(latest, current) > 0,
    url: release.html_url || `https://github.com/${UPDATE_REPO}/releases`,
  };
}

/** 应用菜单(中文标签 + 标准 role 行为/快捷键)。mac 是全局顶部菜单栏;
 *  Win/Linux 菜单栏默认隐藏(无边框自绘标题),Alt 唤起,快捷键始终生效。 */
function buildAppMenu() {
  const isMac = process.platform === "darwin";
  const about = {
    label: "关于 Mosael",
    click: () =>
      dialog.showMessageBox({
        type: "info",
        title: "Mosael",
        message: "Mosael",
        detail: `版本 ${app.getVersion()}`,
        buttons: ["好"],
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
              { role: "services", label: "服务" },
              { type: "separator" },
              { role: "hide", label: "隐藏 Mosael" },
              { role: "hideOthers", label: "隐藏其他" },
              { role: "unhide", label: "全部显示" },
              { type: "separator" },
              { role: "quit", label: "退出 Mosael" },
            ],
          },
        ]
      : []),
    {
      label: "文件",
      submenu: [isMac ? { role: "close", label: "关闭窗口" } : { role: "quit", label: "退出" }],
    },
    {
      label: "编辑",
      submenu: [
        { role: "undo", label: "撤销" },
        { role: "redo", label: "重做" },
        { type: "separator" },
        { role: "cut", label: "剪切" },
        { role: "copy", label: "复制" },
        { role: "paste", label: "粘贴" },
        { role: "selectAll", label: "全选" },
      ],
    },
    {
      label: "视图",
      submenu: [
        // **⌘R 刷的是「你正在看的那一页」。** role:"reload" 永远刷主窗口,而内嵌浏览器占着前台时
        // 用户看到的是平台页面 —— 刷掉主窗口既不符合预期,还会把渲染层重置成"没有内嵌视图"的
        // 初始状态(顶部工具条随之消失,而原生视图还盖在窗口上)。
        {
          label: "重新加载",
          accelerator: "CmdOrCtrl+R",
          click: () => {
            if (publish?.embeddedViewVisible?.()) publish.viewReload();
            else BrowserWindow.getFocusedWindow()?.webContents.reload();
          },
        },
        {
          label: "强制重新加载",
          accelerator: "Shift+CmdOrCtrl+R",
          click: () => {
            if (publish?.embeddedViewVisible?.()) publish.viewReload();
            else BrowserWindow.getFocusedWindow()?.webContents.reloadIgnoringCache();
          },
        },
        { role: "toggleDevTools", label: "开发者工具" },
        { type: "separator" },
        { role: "resetZoom", label: "实际大小" },
        { role: "zoomIn", label: "放大" },
        { role: "zoomOut", label: "缩小" },
        { type: "separator" },
        { role: "togglefullscreen", label: "全屏" },
      ],
    },
    {
      label: "窗口",
      submenu: [
        { role: "minimize", label: "最小化" },
        ...(isMac
          ? [{ role: "zoom", label: "缩放" }, { type: "separator" }, { role: "front", label: "前置全部窗口" }]
          : [{ role: "close", label: "关闭" }]),
      ],
    },
    ...(isMac ? [] : [{ label: "帮助", submenu: [about] }]),
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function createWindow() {
  const isMac = process.platform === "darwin";
  const win = new BrowserWindow({
    show: !isSmokeTest,
    width: 1440,
    height: 900,
    minWidth: 980,
    minHeight: 640,
    title: "Mosael",
    backgroundColor: "#f0f1f3",
    // 无边框标题栏(参考前身项目):mac 红绿灯悬在左上侧栏顶部,
    // Win/Linux 用 titleBarOverlay 把窗口控件叠在右上(高度 = 顶栏 44px)。
    titleBarStyle: "hidden",
    ...(isMac
      ? { trafficLightPosition: { x: 14, y: 15 } }
      : { titleBarOverlay: { color: "#ffffff", symbolColor: "#656c78", height: 44 } }),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });
  // 无边框自绘标题:菜单栏默认隐藏,Win/Linux 下按 Alt 唤起(快捷键始终有效)。
  win.setMenuBarVisibility(false);
  win.autoHideMenuBar = true;
  // 屏幕录制:getDisplayMedia 在 Electron 里需要主进程给出捕获源。优先用系统原生选择器
  // (mac 15+/Win 支持);否则回退到 desktopCapturer 授予主屏。macOS 首次会弹「屏幕录制」系统授权。
  const { desktopCapturer } = require("electron");
  win.webContents.session.setDisplayMediaRequestHandler(
    (_request, callback) => {
      desktopCapturer
        .getSources({ types: ["screen", "window"] })
        .then((sources) => callback(sources[0] ? { video: sources[0] } : {}))
        .catch(() => callback({}));
    },
    { useSystemPicker: true },
  );
  // 全屏时系统窗口控件(mac 红绿灯 / Win 标题栏三键)消失,顶栏为它们预留的边距要撤掉。
  const sendFullscreen = () => {
    if (!win.isDestroyed()) win.webContents.send("mosael:fullscreen", win.isFullScreen());
  };
  win.on("enter-full-screen", sendFullscreen);
  win.on("leave-full-screen", sendFullscreen);
  win.webContents.on("did-finish-load", sendFullscreen);
  // 视图状态是**推的**,渲染层没法主动问。它一旦重新加载(⌘R、HMR、崩溃恢复),PublishViewBar
  // 就回到初始的 visible:false —— 而原生视图还盖在窗口上,表现为「内嵌浏览器还在,顶部工具条没了」。
  // 和上面的全屏状态同一个道理,补播一次。
  win.webContents.on("did-finish-load", () => {
    if (!win.isDestroyed()) publish?.republishViewState?.();
  });
  // 外链(如供应商控制台"获取密钥")走系统浏览器,不在应用内开无控制的新窗口。
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  if (isSmokeTest) {
    win.webContents.once("did-finish-load", () => {
      reportSmoke({ backendHealthy: true, rendererLoaded: true });
      app.quit();
    });
    win.webContents.once("did-fail-load", (_event, code, description) => {
      reportSmoke({ backendHealthy: true, rendererLoaded: false, error: `${code}: ${description}` });
      app.exit(1);
    });
  }
  if (isDev) {
    win.loadURL(process.env.MOSAEL_FRONTEND_URL || "http://127.0.0.1:5173");
  } else {
    win.loadFile(path.join(__dirname, "..", "frontend", "dist", "index.html"));
  }

  // 启动发布执行器:后端是任务事实源,这里驱动每账号一个持久登录的内嵌视图。
  // mac 关窗→重新激活会重建窗口:先 stop 再 start,把视图挂到新窗口上。
  if (publish) {
    try {
      publish.stopPublishWorker();
      publish.startPublishWorker({
        window: win,
        onViewChanged: (state) => {
          if (!win.isDestroyed()) win.webContents.send("publish:view", state);
        },
        // 悬浮卡片几何:原生 WebContentsView 画不了圆角/阴影,所以渲染层照这些矩形在视图**下方**
        // 画卡片外壳(子视图永远盖在宿主页面之上,于是卡片的圆角边框会在视图四周露出来)。
        onPanels: (cards) => {
          if (!win.isDestroyed()) win.webContents.send("publish:panels", cards);
        },
        // 发布任务在后台不可见的账号视图里跑,用户否则完全看不到它在做什么。走与 RPA 相同的
        // browser:frame 通道和同一个前端面板——「自动化浏览器在干什么」对用户是一件事,不该
        // 因为内部分了两个 worker 就冒出两个窗口。
        onFrame: (frame) => {
          if (!win.isDestroyed()) win.webContents.send("browser:frame", frame);
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
          const titles = {
            login_required: "账号需要登录",
            waiting_manual: "发布需要人工处理",
            permission_required: "账号权限不足",
            blocked: "发布被拦截",
          };
          // success / failed / cancelled 交给 TaskCenter(它按 job 终态发,标签和其它任务一致)。
          if (!titles[info.status]) return;
          const notice = {
            title: titles[info.status],
            body: `${info.accountName} · ${info.title || "未命名"}`,
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
      console.warn("[publish] 启动执行器失败:", e.message);
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
      console.warn("[browser] 启动执行器失败:", e.message);
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
  const ready = await ensureBackend();
  if (!ready) {
    reportSmoke({ backendHealthy: false, rendererLoaded: false, error: "backend did not become healthy" });
    if (isSmokeTest) {
      app.exit(1);
      return;
    }
    dialog.showErrorBox(
      "Mosael backend failed to start",
      `The local backend did not become healthy on port ${BACKEND_PORT}. ` +
        "Check that the port is free and see logs in ~/.mosael/logs if available.",
    );
    app.quit();
    return;
  }
  // publish:* handler 只注册一次(activate 重建窗口时不能二次注册)。恒注册:执行器加载失败时
  // 也给渲染层抛清晰错误。
  const requirePublish = () => {
    if (publish) return publish;
    throw new Error(
      publishLoadError
        ? `发布执行器加载失败:${publishLoadError.message}`
        : "发布执行器不可用:electron/publish.bundle.cjs 缺失(先跑 pnpm build:publisher)",
    );
  };
  ipcMain.handle("publish:login", (_e, { accountId, platform }) => requirePublish().openLogin(accountId, platform));
  ipcMain.handle("publish:openPage", (_e, { accountId, platform }) => requirePublish().openPage(accountId, platform));
  ipcMain.handle("publish:inspect", (_e, { accountId, platform }) => requirePublish().inspectAccount(accountId, platform));
  ipcMain.handle("publish:navigate", (_e, { url }) => requirePublish().navigateView(url));
  ipcMain.handle("publish:back", () => requirePublish().viewBack());
  ipcMain.handle("publish:forward", () => requirePublish().viewForward());
  ipcMain.handle("publish:reload", () => requirePublish().viewReload());
  ipcMain.handle("publish:hideView", () => requirePublish().hidePublishView());
  // 悬浮面板:渲染层拖动/缩放/关闭。几何由主进程持有(layout() 要用,还要落盘)。
  ipcMain.handle("publish:panelLayout", (_e, patch) => requirePublish().setPanelLayout(patch || {}));
  ipcMain.handle("publish:closePanel", (_e, { id }) => requirePublish().closePanel(id));
  // 通用池档案登录:复用发布账号那套 app **内嵌视图**(不弹外部系统窗,体验与发布登录一致)。
  // 安全:只放行 persist:pool-* 分区(发布账号走 publish:login),只放行 http(s)。
  ipcMain.handle("browser:openLogin", async (_e, { partition, url, name, proxy }) => {
    try {
      const part = String(partition || "");
      if (!part.startsWith("persist:pool-")) return { ok: false, error: "只支持通用池档案的登录" };
      const target = String(url || "").trim();
      if (!/^https?:\/\//i.test(target)) return { ok: false, error: "请输入 http(s) 网址" };
      await requirePublish().openPoolLogin({ partition: part, url: target, name: name || "", proxy: proxy ?? null });
      return { ok: true };
    } catch (err) {
      return { ok: false, error: String(err && err.message ? err.message : err) };
    }
  });
  // 账号视图里注入的「返回 Mosael」按钮(account-view-preload.cjs)→ 收起内嵌视图。
  ipcMain.on("publish:exit", () => {
    try {
      requirePublish().hidePublishView();
    } catch (e) {
      console.warn("[publish] exit 忽略:", e.message);
    }
  });

  // 更新检查:设置页「检查更新」按钮主动调;打包版启动后再静默查一次,
  // 有新版把信息推给渲染层弹提示。检查失败(离线/私有仓库)不打扰。
  ipcMain.handle("mosael:check-updates", async () => {
    try {
      return await checkForUpdates();
    } catch (error) {
      return { error: error.message };
    }
  });
  if (app.isPackaged && !isSmokeTest) {
    setTimeout(async () => {
      try {
        const info = await checkForUpdates();
        if (info.hasUpdate) {
          for (const win of BrowserWindow.getAllWindows()) win.webContents.send("mosael:update-available", info);
        }
      } catch {
        /* 静默 */
      }
    }, 5000);
  }

  buildAppMenu();
  // 关于面板信息(mac 标准关于弹窗)。
  app.setAboutPanelOptions({ applicationName: "Mosael", applicationVersion: app.getVersion() });
  // Dock 图标:打包版走 .icns;开发态未打包时 Dock 用的是 Electron 默认图标,这里用打进仓库的
  // build/icon.png 覆盖(路径不存在时 createFromPath 返回空图,跳过)。
  if (process.platform === "darwin" && app.dock) {
    const dockIcon = nativeImage.createFromPath(path.join(__dirname, "..", "build", "icon.png"));
    if (!dockIcon.isEmpty()) app.dock.setIcon(dockIcon);
  }
  // Win/Linux:标题栏三键叠层颜色随前端主题(mosaelDesktop.setTitleOverlay)。mac 无叠层。
  ipcMain.on("mosael:title-overlay", (event, colors) => {
    if (process.platform === "darwin" || !colors) return;
    const win = BrowserWindow.fromWebContents(event.sender);
    try {
      win?.setTitleBarOverlay({ color: colors.color, symbolColor: colors.symbolColor, height: 44 });
    } catch {
      // 老版本 / 非 overlay 窗口:忽略。
    }
  });

  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });

  // 系统能力:窗口建好之后再注册(residency 要挂到窗口的 close 上)。
  if (system) {
    const showWindow = () => {
      let win = BrowserWindow.getAllWindows()[0];
      if (!win || win.isDestroyed()) {
        createWindow();
        win = BrowserWindow.getAllWindows()[0];
      }
      if (!win) return;
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
    };
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
    ipcMain.on("system:status", (_e, status) => systemHandle?.pushStatus(status || {}));
    // 渲染层在任务结束时调用。发不发由主进程判(窗口藏起来时渲染层的 hasFocus 不可靠)。
    ipcMain.on("system:notify", (_e, notice) => {
      if (notice?.title) system.showTaskNotification({ title: String(notice.title), body: String(notice.body || "") });
    });
    // 开发模式返回 null = 「本环境不支持」,设置页据此隐藏开关。不能只是让它失效:
    // dev 下 process.execPath 是 Electron 二进制,写进登录项等于让开发机开机启动一个裸 Electron。
    ipcMain.handle("system:getOpenAtLogin", () => (isDev ? null : system.getOpenAtLogin()));
    ipcMain.handle("system:setOpenAtLogin", (_e, enabled) => (isDev ? null : system.setOpenAtLogin(Boolean(enabled))));

    // 自定义 CSS:渲染层要三样东西 —— 内容(启动时读一次,之后靠推送)、路径(设置页显示)、
    // 以及打开/定位这个文件的两个动作。写入始终由用户在自己的编辑器里完成,应用不代写。
    ipcMain.handle("customCss:read", () => system.readCustomCss());
    ipcMain.handle("customCss:path", () => system.customCssPath());
    ipcMain.handle("customCss:open", () => system.openCustomCss());
    ipcMain.handle("customCss:reveal", () => system.revealCustomCss());

    // 开机自启拉起时静默驻留托盘,不弹窗口。
    if (system.isHiddenLaunch()) BrowserWindow.getAllWindows()[0]?.hide();
  }
});

// 关窗不退:窗口只是隐藏(见 system/residency),托盘是应用还活着的可见入口。定时任务
// 依赖后端进程活着,而后端是主进程 spawn 的子进程 —— 以前这里 app.quit() 等于「关窗就把
// 定时任务一起关了」。系统能力没加载成功时退回老行为,否则应用会变成关不掉的幽灵进程。
app.on("window-all-closed", () => {
  if (!system && process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  quitting = true;
  systemHandle?.dispose();
  stopBackend();
});

app.on("will-quit", stopBackend);
process.on("exit", stopBackend);
