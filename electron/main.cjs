const { app, BrowserWindow } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");

let backend = null;

function startBackend() {
  if (backend) return;
  const cwd = path.resolve(__dirname, "../backend");
  backend = spawn("uv", ["run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8800"], {
    cwd,
    stdio: "inherit",
  });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 820,
    title: "Mibu New",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadURL(process.env.MIBU_FRONTEND_URL || "http://127.0.0.1:5173");
}

app.whenReady().then(() => {
  startBackend();
  createWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  if (backend && !backend.killed) backend.kill();
});

