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

  /** 本机的 Developer ID Application 证书(有就用它签,TCC 才会把 dev 应用当成同一个应用)。 */
  const developerIdIdentity = () => {
    try {
      const output = execFileSync("/usr/bin/security", ["find-identity", "-v", "-p", "codesigning"]).toString();
      const match = /"((?:Developer ID Application|Apple Development)[^"]+)"/.exec(output);
      return match ? match[1] : null;
    } catch {
      return null;
    }
  };

  const signatureIsValid = () => {
    try {
      execFileSync("/usr/bin/codesign", ["--verify", "--deep", "--strict", app], { stdio: "ignore" });
      return true;
    } catch {
      return false;
    }
  };
  /** 当前签名是谁签的(ad-hoc 时是空串)。 */
  const currentAuthority = () => {
    try {
      const output = execFileSync("/usr/bin/codesign", ["-dv", "--verbose=2", app], { stdio: ["ignore", "ignore", "pipe"] });
      return output.toString();
    } catch (error) {
      // codesign 把详情写到 stderr;execFileSync 失败时 error.stderr 里就是它。
      return String(error && error.stderr ? error.stderr : "");
    }
  };
  const wantedIdentity = developerIdIdentity();
  const signedByWanted = wantedIdentity ? currentAuthority().includes(wantedIdentity) : currentAuthority().includes("Signature=adhoc");
  if (changed || !signatureIsValid() || !signedByWanted) {
    // Preserve Electron's helper entitlements while replacing the now-invalid outer signature.
    // The dedicated dev identifier deliberately stays separate from the packaged app's identity.
    //
    // **为什么优先用本机的 Developer ID,而不是 ad-hoc(`-`)**:TCC(屏幕/摄像头/麦克风授权)按
    // 「bundle id + 签名身份」认应用。ad-hoc 签名每次重建都换一个 cdhash,系统把它当成**另一个
    // 应用** —— 于是「屏幕与系统音频录制」列表里永远不出现 Mosael,也没有授权可复用(维护者
    // 2026-10-23 连问两次:「列表中依然没有 Mosael」)。用 Developer ID 签,身份稳定,历史登录
    // 一次授权之后,后面每次 dev 重建都还认它。本机没这个证书时照旧退回 ad-hoc,不阻塞开发。
    execFileSync("/usr/bin/codesign", [
      "--force",
      "--deep",
      "--sign",
      wantedIdentity ?? "-",
      "--preserve-metadata=entitlements,requirements,flags,runtime",
      app,
    ]);
    console.log(`[brand-dev] signed with ${wantedIdentity ?? "ad-hoc signature"}`);
  }
  // 触碰 .app 让 LaunchServices 刷新名称缓存。
  try {
    execFileSync("/usr/bin/touch", [app]);
  } catch {
    /* ignore */
  }
  console.log("[brand-dev] Electron.app is now a standalone, validly signed Mosael (dev)");
} catch (error) {
  console.warn("[brand-dev] skipped:", error.message);
}
