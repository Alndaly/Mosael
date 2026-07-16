const { app, BrowserWindow, Notification, dialog, ipcMain } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");

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
  backend = spawn(command, args, {
    cwd,
    env: { ...process.env, MIBU_BACKEND_PORT: String(BACKEND_PORT) },
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

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 980,
    minHeight: 640,
    title: "Mibu",
    backgroundColor: "#f0f1f3",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });
  win.setMenuBarVisibility(false);
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

  win.on("closed", () => {
    try {
      publish?.stopPublishWorker();
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
        "Check that the port is free and see logs in ~/.mibu-new/logs if available.",
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
  ipcMain.handle("publish:hideView", () => requirePublish().hidePublishView());
  // 账号视图里注入的「返回 Mibu」按钮(accountview-preload.cjs)→ 收起内嵌视图。
  ipcMain.on("publish:exit", () => {
    try {
      requirePublish().hidePublishView();
    } catch (e) {
      console.warn("[publish] exit 忽略:", e.message);
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
