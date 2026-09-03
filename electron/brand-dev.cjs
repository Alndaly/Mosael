// dev-only:给未打包的 Electron.app 一个稳定、独立的 Mosael 身份。
// 只改 CFBundleName 会破坏 Electron 原有签名,而屏幕/摄像头/麦克风权限由 TCC 按 bundle 身份
// 和代码签名登记,结果就是系统设置里不出现 Mosael 或授权无法复用。因此这里同时设置独立的
// dev bundle id、权限用途说明,并在修改后做一次 ad-hoc 重签。打包版由 electron-builder 负责。
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
  const expected = {
    CFBundleIdentifier: "dev.mosael.app.dev",
    CFBundleName: "Mosael",
    CFBundleDisplayName: "Mosael",
    NSCameraUsageDescription: "Mosael needs camera access when you record a camera asset.",
    NSMicrophoneUsageDescription: "Mosael needs microphone access when you record narration or a camera asset.",
    NSAudioCaptureUsageDescription:
      "Mosael needs access to system audio when you include device audio in a screen recording.",
  };
  let changed = false;
  for (const [key, value] of Object.entries(expected)) {
    if (read(key) === value) continue;
    // Set 已存在的键;不存在则 Add。
    try {
      execFileSync("/usr/libexec/PlistBuddy", ["-c", `Set :${key} ${value}`, plist]);
    } catch {
      execFileSync("/usr/libexec/PlistBuddy", ["-c", `Add :${key} string ${value}`, plist]);
    }
    changed = true;
  }

  const signatureIsValid = () => {
    try {
      execFileSync("/usr/bin/codesign", ["--verify", "--deep", "--strict", app], { stdio: "ignore" });
      return true;
    } catch {
      return false;
    }
  };
  if (changed || !signatureIsValid()) {
    // Preserve Electron's helper entitlements while replacing the now-invalid outer signature.
    // The dedicated dev identifier deliberately stays separate from the packaged app's identity.
    execFileSync("/usr/bin/codesign", [
      "--force",
      "--deep",
      "--sign",
      "-",
      "--preserve-metadata=entitlements,requirements,flags,runtime",
      app,
    ]);
  }
  // 触碰 .app 让 LaunchServices 刷新名称缓存。
  try {
    execFileSync("/usr/bin/touch", [app]);
  } catch {
    /* ignore */
  }
  console.log("[brand-dev] Electron.app 已设置为独立且签名有效的 Mosael(dev)");
} catch (error) {
  console.warn("[brand-dev] 跳过:", error.message);
}
