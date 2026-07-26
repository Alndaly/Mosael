const { app, BrowserWindow, Menu, Notification, dialog, ipcMain, nativeImage, shell } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");

// 应用名。开发态跑的是未打包的 Electron.app,菜单栏首项 / Dock 名默认显示 "Electron"。
// macOS dev 的菜单/Dock 名读 Electron.app 的 CFBundleName,由 electron/brand-dev.cjs 在启动前补丁;
// 这里的 setName 影响 app.getName()/部分弹窗,setAppUserModelId 影响 Windows 任务栏归组。
// 打包版统一由 electron-builder 的 productName 决定。必须在 app ready 前调用。
app.setName("Mibu");
app.setAppUserModelId("dev.mibu.studio");

// 发布内嵌浏览器拟真:引擎层去掉自动化标记(navigator.webdriver 等),让平台风控不把用户
// 授权的自动化发布误判为爬虫。页面级补丁见 electron/publish/stealth.ts。
app.commandLine.appendSwitch("disable-blink-features", "AutomationControlled");

const BACKEND_PORT = Number(process.env.MIBU_BACKEND_PORT || 8800);
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const isDev = !app.isPackaged;

let backend = null;
let quitting = false;

// 发布执行器(老版 mibu-video 移植):esbuild 打成的单文件 bundle,缺失/损坏不挡应用启动,
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
    return {
      command: path.join(backendDir, ".venv", "bin", "uvicorn"),
      args: ["app.main:app", "--host", "127.0.0.1", "--port", String(BACKEND_PORT)],
      cwd: backendDir,
    };
  }
  const packagedDir = path.join(process.resourcesPath, "backend", "mibu-backend");
  const executable = process.platform === "win32" ? "mibu-backend.exe" : "mibu-backend";
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
  // Port already serving a healthy Mibu backend (e.g. dev uvicorn) → reuse it.
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
  const backendEnv = { ...process.env, MIBU_BACKEND_PORT: String(BACKEND_PORT) };
  if (!isDev) {
    // 打包版:pi sidecar 随资源分发,用 Electron 二进制(当 node)拉起
    backendEnv.MIBU_PI_SIDECAR = path.join(process.resourcesPath, "agent-sidecar", "sidecar.cjs");
    backendEnv.MIBU_AGENT_BIN_NODE = process.execPath;
  }
  backend = spawn(command, args, {
    cwd,
    env: backendEnv,
    stdio,
  });
  backend.on("exit", (code) => {
    backend = null;
    if (!quitting && code !== 0 && code !== null) {
      dialog.showErrorBox("Mibu backend stopped", `The local backend exited unexpectedly (code ${code}). Please restart Mibu.`);
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
const UPDATE_REPO = "Alndaly/mibu-cut";

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
    headers: { Accept: "application/vnd.github+json", "User-Agent": "mibu-updater" },
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
    label: "关于 Mibu",
    click: () =>
      dialog.showMessageBox({
        type: "info",
        title: "Mibu",
        message: "Mibu",
        detail: `版本 ${app.getVersion()}`,
        buttons: ["好"],
      }),
  };
  const template = [
    ...(isMac
      ? [
          {
            label: "Mibu",
            submenu: [
              about,
              { type: "separator" },
              { role: "services", label: "服务" },
              { type: "separator" },
              { role: "hide", label: "隐藏 Mibu" },
              { role: "hideOthers", label: "隐藏其他" },
              { role: "unhide", label: "全部显示" },
              { type: "separator" },
              { role: "quit", label: "退出 Mibu" },
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
    title: "Mibu",
    backgroundColor: "#f0f1f3",
    // 无边框标题栏(参考 mibu-video):mac 红绿灯悬在左上侧栏顶部,
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
    if (!win.isDestroyed()) win.webContents.send("mibu:fullscreen", win.isFullScreen());
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
    win.loadURL(process.env.MIBU_FRONTEND_URL || "http://127.0.0.1:5173");
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
  // onFrame 把「最近操作的会话」的截帧推给前端做实时预览(离屏自动化视图否则看不到)。
  if (publish && publish.startBrowserWorker) {
    try {
      publish.stopBrowserWorker();
      publish.startBrowserWorker({
        window: win,
        onFrame: (frame) => {
          if (!win.isDestroyed()) win.webContents.send("browser:frame", frame);
        },
      });
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
      "Mibu backend failed to start",
      `The local backend did not become healthy on port ${BACKEND_PORT}. ` +
        "Check that the port is free and see logs in ~/.mibu-cut/logs if available.",
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
  // 通用池档案的可见登录窗:在该分区(persist:pool-*)开一个独立窗口登任意站点。用户登完关窗、
  // cookie 落盘,之后工作流/智能体用该档案复用登录。安全:只放行 persist:pool-* 分区(发布账号
  // 走 publish:login);只放行 http(s);不挂 mibu 预载(第三方站点不该拿到任何应用 API)。
  ipcMain.handle("browser:openLogin", async (_e, { partition, url }) => {
    try {
      const part = String(partition || "");
      if (!part.startsWith("persist:pool-")) return { ok: false, error: "只支持通用池档案的登录窗" };
      const target = String(url || "").trim();
      if (!/^https?:\/\//i.test(target)) return { ok: false, error: "请输入 http(s) 网址" };
      const win = new BrowserWindow({
        width: 1100,
        height: 780,
        title: "登录",
        autoHideMenuBar: true,
        webPreferences: { partition: part, contextIsolation: true, nodeIntegration: false },
      });
      await win.loadURL(target);
      return { ok: true };
    } catch (err) {
      return { ok: false, error: String(err && err.message ? err.message : err) };
    }
  });
  // 账号视图里注入的「返回 Mibu」按钮(accountview-preload.cjs)→ 收起内嵌视图。
  ipcMain.on("publish:exit", () => {
    try {
      requirePublish().hidePublishView();
    } catch (e) {
      console.warn("[publish] exit 忽略:", e.message);
    }
  });

  // 更新检查:设置页「检查更新」按钮主动调;打包版启动后再静默查一次,
  // 有新版把信息推给渲染层弹提示。检查失败(离线/私有仓库)不打扰。
  ipcMain.handle("mibu:check-updates", async () => {
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
          for (const win of BrowserWindow.getAllWindows()) win.webContents.send("mibu:update-available", info);
        }
      } catch {
        /* 静默 */
      }
    }, 5000);
  }

  buildAppMenu();
  // 关于面板信息(mac 标准关于弹窗)。
  app.setAboutPanelOptions({ applicationName: "Mibu", applicationVersion: app.getVersion() });
  // Dock 图标:打包版走 .icns;开发态未打包时 Dock 用的是 Electron 默认图标,这里用打进仓库的
  // build/icon.png 覆盖(路径不存在时 createFromPath 返回空图,跳过)。
  if (process.platform === "darwin" && app.dock) {
    const dockIcon = nativeImage.createFromPath(path.join(__dirname, "..", "build", "icon.png"));
    if (!dockIcon.isEmpty()) app.dock.setIcon(dockIcon);
  }
  // Win/Linux:标题栏三键叠层颜色随前端主题(mibuDesktop.setTitleOverlay)。mac 无叠层。
  ipcMain.on("mibu:title-overlay", (event, colors) => {
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
