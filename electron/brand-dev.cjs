// dev-only:让未打包的 Electron.app 在 macOS 菜单栏/Dock 显示 "Mosael"。
// macOS 的应用名读 Electron.app 的 CFBundleName/CFBundleDisplayName,app.setName() 在 dev 下压不住;
// 打包版由 electron-builder 的 productName 决定,无需此步。
// 改的是本地 node_modules 里的 Electron.app —— 重装 electron 会重置,所以每次 dev 启动前跑一次(幂等)。
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

if (process.platform !== "darwin") process.exit(0);

try {
  // electron 可能被 pnpm 提升到根 node_modules,也可能在 frontend 下;都试。
  const candidates = [
    path.join(__dirname, "..", "node_modules", "electron", "dist", "Electron.app"),
    path.join(__dirname, "..", "frontend", "node_modules", "electron", "dist", "Electron.app"),
  ];
  const app = candidates.find((p) => fs.existsSync(p));
  if (!app) process.exit(0);

  const plist = path.join(app, "Contents", "Info.plist");
  const read = (key) => {
    try {
      return execFileSync("/usr/libexec/PlistBuddy", ["-c", `Print :${key}`, plist]).toString().trim();
    } catch {
      return "";
    }
  };
  if (read("CFBundleName") === "Mosael" && read("CFBundleDisplayName") === "Mosael") process.exit(0);

  for (const key of ["CFBundleName", "CFBundleDisplayName"]) {
    // Set 已存在的键;不存在则 Add。
    try {
      execFileSync("/usr/libexec/PlistBuddy", ["-c", `Set :${key} Mosael`, plist]);
    } catch {
      execFileSync("/usr/libexec/PlistBuddy", ["-c", `Add :${key} string Mosael`, plist]);
    }
  }
  // 触碰 .app 让 LaunchServices 刷新名称缓存。
  try {
    execFileSync("/usr/bin/touch", [app]);
  } catch {
    /* ignore */
  }
  console.log("[brand-dev] Electron.app 已改名为 Mosael(dev)");
} catch (error) {
  console.warn("[brand-dev] 跳过:", error.message);
}
