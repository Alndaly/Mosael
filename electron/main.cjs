const { app, BrowserWindow, Menu, Notification, dialog, ipcMain, nativeImage, shell } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");

// 应用名。开发态跑的是未打包的 Electron.app,菜单栏首项 / Dock 名默认显示 "Electron"。
// macOS dev 的菜单/Dock 名读 Electron.app 的 CFBundleName,由 electron/brand-dev.cjs 在启动前补丁;
// 这里的 setName 影响 app.getName()/部分弹窗,setAppUserModelId 影响 Windows 任务栏归组。
// 打包版统一由 electron-builder 的 productName 决定。必须在 app ready 前调用。
app.setName("Open Studio");
// 保留旧的 AppUserModelId(Windows 任务栏归组的不透明 id;改了等于换一个应用,得不偿失)。
app.setAppUserModelId("dev.openstudio.app");

// 更名(Mibu → Open Studio)迁移:userData = appData/app.getName(),改名会把登录分区
// (Partitions)与日志留在旧目录下。启动最早、任何 userData 使用之前,把旧目录整体平移到
// 新名下(仅当新目录尚不存在)。失败不致命——大不了当作全新安装。
try {
  const fs = require("node:fs");
  const appData = app.getPath("appData");
  const newUserData = path.join(appData, app.getName());
  // 旧名大小写不确定(setName 曾为 "Mibu",打包/文档里也见过小写 "mibu"),两者都试一遍。
  if (!fs.existsSync(newUserData)) {
    for (const legacy of ["Mibu", "mibu"]) {
      const oldUserData = path.join(appData, legacy);
      if (oldUserData !== newUserData && fs.existsSync(oldUserData)) {
        fs.renameSync(oldUserData, newUserData);
        break;
      }
    }
  }
} catch (err) {
  console.warn("[open-studio] userData migration skipped:", err);
}

// 发布内嵌浏览器拟真:引擎层去掉自动化标记(navigator.webdriver 等),让平台风控不把用户
// 授权的自动化发布误判为爬虫。页面级补丁见 electron/publish/stealth.ts。
app.commandLine.appendSwitch("disable-blink-features", "AutomationControlled");

const BACKEND_PORT = Number(process.env.OPEN_STUDIO_BACKEND_PORT || 8800);
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const isDev = !app.isPackaged;

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

function backendCommand() {
  if (isDev) {
    const backendDir = path.resolve(__dirname, "../backend");
    // 走 `python -m uvicorn` 而不是 .venv/bin/uvicorn:后者是带 shebang 的 console script,
    // 解释器路径在建 venv 时被**写死成绝对路径**——仓库目录一改名(mibu-cut → OpenStudio 就发生过),
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
  const packagedDir = path.join(process.resourcesPath, "backend", "open-studio-backend");
  const executable = process.platform === "win32" ? "open-studio-backend.exe" : "open-studio-backend";
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
  // Port already serving a healthy Open Studio backend (e.g. dev uvicorn) → reuse it.
  if (await isHealthy()) return true;

  const { command, args, cwd } = backendCommand();
  // 打包版后端日志落盘(userData/logs/backend.log);之前 ignore 导致后端问题完全无迹可查。
  let stdio = "inherit";
  if (!isDev) {
    try {
      const fs = require("node:fs");
      const logDir = path.join(app.getPath("userData"), "logs");
      fs.mkdirSync(logDir, { recursive: true });
      const fd = fs.openSync(path.join(logDir, "backend.log"), "a");
      stdio = ["ignore", fd, fd];
    } catch {
      stdio = "ignore";
    }
  }
  const backendEnv = { ...process.env, OPEN_STUDIO_BACKEND_PORT: String(BACKEND_PORT) };
  if (!isDev) {
    // 打包版:pi sidecar 随资源分发,用 Electron 二进制(当 node)拉起
    backendEnv.OPEN_STUDIO_PI_SIDECAR = path.join(process.resourcesPath, "agent-sidecar", "sidecar.cjs");
    backendEnv.OPEN_STUDIO_AGENT_BIN_NODE = process.execPath;
    // 声音克隆的运行环境由后端在用户数据目录里自建(见 domain/tts_config.MANAGED_TTS_VENV),
    // 但打包版后端是 PyInstaller 冻结二进制,建不了 venv——所以把随包分发的独立解释器指给它。
    // 只带解释器(~40MB),torch 等数 GB 依赖点「下载」时才装,不进安装包。
    const fsMod = require("node:fs");
    const ttsPython = path.join(
      process.resourcesPath,
      "python",
      process.platform === "win32" ? "python.exe" : path.join("bin", "python3"),
    );
    if (fsMod.existsSync(ttsPython)) backendEnv.OPEN_STUDIO_TTS_BASE_PYTHON = ttsPython;
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
      dialog.showErrorBox("Open Studio backend stopped", `The local backend exited unexpectedly (code ${code}). Please restart Open Studio.`);
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
const UPDATE_REPO = "Alndaly/OpenStudio";

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
    headers: { Accept: "application/vnd.github+json", "User-Agent": "open-studio-updater" },
  });
  if (!res.ok) throw new Error(`GitHub ${res.status}`);
  const release = await res.json();
  const latest = String(release.tag_name || "").replace(/^v/i, "");
  const current = app.getVersion();
  return {
    current,
    latest,
    hasUpdate: Boolean(latest) && compareVersions(latest, current) > 0,
    url: release.html_url || `https://github.com/${UPDATE_REPO}/releases`,
  };
}

/** 应用菜单(中文标签 + 标准 role 行为/快捷键)。mac 是全局顶部菜单栏;
 *  Win/Linux 菜单栏默认隐藏(无边框自绘标题),Alt 唤起,快捷键始终生效。 */
function buildAppMenu() {
  const isMac = process.platform === "darwin";
  const about = {
    label: "关于 Open Studio",
    click: () =>
      dialog.showMessageBox({
        type: "info",
        title: "Open Studio",
        message: "Open Studio",
        detail: `版本 ${app.getVersion()}`,
        buttons: ["好"],
      }),
  };
  const template = [
    ...(isMac
      ? [
          {
            label: "Open Studio",
            submenu: [
              about,
              { type: "separator" },
              { role: "services", label: "服务" },
              { type: "separator" },
              { role: "hide", label: "隐藏 Open Studio" },
              { role: "hideOthers", label: "隐藏其他" },
              { role: "unhide", label: "全部显示" },
              { type: "separator" },
              { role: "quit", label: "退出 Open Studio" },
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
        { role: "reload", label: "重新加载" },
        { role: "forceReload", label: "强制重新加载" },
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
    width: 1440,
    height: 900,
    minWidth: 980,
    minHeight: 640,
    title: "Open Studio",
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
    if (!win.isDestroyed()) win.webContents.send("openstudio:fullscreen", win.isFullScreen());
  };
  win.on("enter-full-screen", sendFullscreen);
  win.on("leave-full-screen", sendFullscreen);
  win.webContents.on("did-finish-load", sendFullscreen);
  // 外链(如供应商控制台"获取密钥")走系统浏览器,不在应用内开无控制的新窗口。
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  if (isDev) {
    win.loadURL(process.env.OPEN_STUDIO_FRONTEND_URL || "http://127.0.0.1:5173");
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
        onTaskSettled: (info) => {
          const titles = {
            success: "发布成功",
            prepared: "发布已准备好,待确认",
            failed: "发布失败",
            login_required: "账号需要登录",
            waiting_manual: "发布需要人工处理",
            permission_required: "账号权限不足",
            blocked: "发布被拦截",
          };
          if (Notification.isSupported()) {
            new Notification({
              title: titles[info.status] || `发布 ${info.status}`,
              body: `${info.accountName} · ${info.title || "未命名"}`,
            }).show();
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
    dialog.showErrorBox(
      "Open Studio backend failed to start",
      `The local backend did not become healthy on port ${BACKEND_PORT}. ` +
        "Check that the port is free and see logs in ~/.open-studio/logs if available.",
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
  // 账号视图里注入的「返回 Open Studio」按钮(account-view-preload.cjs)→ 收起内嵌视图。
  ipcMain.on("publish:exit", () => {
    try {
      requirePublish().hidePublishView();
    } catch (e) {
      console.warn("[publish] exit 忽略:", e.message);
    }
  });

  // 更新检查:设置页「检查更新」按钮主动调;打包版启动后再静默查一次,
  // 有新版把信息推给渲染层弹提示。检查失败(离线/私有仓库)不打扰。
  ipcMain.handle("openstudio:check-updates", async () => {
    try {
      return await checkForUpdates();
    } catch (error) {
      return { error: error.message };
    }
  });
  if (app.isPackaged) {
    setTimeout(async () => {
      try {
        const info = await checkForUpdates();
        if (info.hasUpdate) {
          for (const win of BrowserWindow.getAllWindows()) win.webContents.send("openstudio:update-available", info);
        }
      } catch {
        /* 静默 */
      }
    }, 5000);
  }

  buildAppMenu();
  // 关于面板信息(mac 标准关于弹窗)。
  app.setAboutPanelOptions({ applicationName: "Open Studio", applicationVersion: app.getVersion() });
  // Dock 图标:打包版走 .icns;开发态未打包时 Dock 用的是 Electron 默认图标,这里用打进仓库的
  // build/icon.png 覆盖(路径不存在时 createFromPath 返回空图,跳过)。
  if (process.platform === "darwin" && app.dock) {
    const dockIcon = nativeImage.createFromPath(path.join(__dirname, "..", "build", "icon.png"));
    if (!dockIcon.isEmpty()) app.dock.setIcon(dockIcon);
  }
  // Win/Linux:标题栏三键叠层颜色随前端主题(openStudioDesktop.setTitleOverlay)。mac 无叠层。
  ipcMain.on("openstudio:title-overlay", (event, colors) => {
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
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  quitting = true;
  stopBackend();
});

app.on("will-quit", stopBackend);
process.on("exit", stopBackend);
