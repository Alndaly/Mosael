/**
 * main.cjs 里和窗口、后端生命周期有关的接法(规则本身在 backend-lifecycle / renderer-recovery / window-bounds 里各有测试,
 * 这里钉住 main.cjs 真的用了它们,而不是又写回老样子)。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

import { describe, expect, it, vi } from "vitest";

const MAIN = fs.readFileSync(path.join(__dirname, "main.cjs"), "utf8");

describe("后端", () => {
  it("启动时不再按固定 30 秒判失败:交给 backendSupervisor,只要进程活着就等,等久了亮「正在启动」小窗", () => {
    expect(MAIN).not.toMatch(/waitForBackend\(|30000|30_000/);
    expect(MAIN).toMatch(/backendSupervisor\.start\(\{\s*initial: true,/);
    expect(MAIN).toMatch(/splash\.show\(\)/);
  });

  it("连崩认输不用模态的 showErrorBox(那会把整个主进程卡在一个框上),给「再试一次」", () => {
    expect(MAIN).toMatch(/onGiveUp: \(lastExit\) => void askAfterBackendGaveUp\(lastExit\)/);
    expect(MAIN).toMatch(/async function askAfterBackendGaveUp[\s\S]{0,700}backendSupervisor\.retry\(\)/);
    expect(MAIN).toMatch(/handle\(IPC\.invoke\.backendRetry,/);
  });

  it("报错框里的日志目录是真的那两处(userData/logs 和数据目录的 logs),不再写死 ~/.mosael/logs", () => {
    expect(MAIN).toMatch(/const logPlaces = \(\) => \(\{ logs: electronLogDir, dataLogs: path\.join\(configuredDataDir, "logs"\) \}\)/);
    expect(fs.readFileSync(path.join(__dirname, "i18n.cjs"), "utf8")).not.toMatch(/~\/\.mosael\/logs/);
  });

  it("退出时:Windows 先请后端收尾、等它退,再让壳退;别的平台发一次 SIGTERM", () => {
    expect(MAIN).toMatch(/if \(backendSupervisor\.needsGracefulShutdown\(\)\) \{\s*event\.preventDefault\(\);\s*void backendSupervisor\.shutdown\(\)\.finally/);
    expect(MAIN).toMatch(/\/api\/health\/shutdown/);
  });
});

describe("窗口", () => {
  it("主窗口建出来之前关掉「正在启动」小窗,不算窗口全关了", () => {
    expect(MAIN).toMatch(/app\.on\("window-all-closed", \(\) => \{\s*if \(!mainWindowCreated\) return;/);
  });

  it("渲染进程崩了自动重新载入;界面崩了时 ⌘R 先救界面,不去刷内嵌网页", () => {
    expect(MAIN).toMatch(/win\.webContents\.on\("render-process-gone", \(_event, details\) => \{\s*publish\?\.releaseWorkbenchView\?\.\(\);\s*recover\(details\);/);
    expect(MAIN.match(/embeddedViewVisible\?\.\(\) && !win\?\.webContents\.isCrashed\(\)/g)).toHaveLength(2);
  });

  it("照上次的位置大小打开,改了就记下来", () => {
    expect(MAIN).toMatch(/\.\.\.placement\.bounds,/);
    expect(MAIN).toMatch(/rememberWindowBounds\(win, windowStateFile\)/);
  });
});

describe("视图 → 放大 / 缩小", () => {
  /** 从 main.cjs 取出 zoomWindow 本身跑。 */
  function loadZoomWindow() {
    const source = MAIN.match(/\nfunction zoomWindow\(change\) \{[\s\S]*?\n\}\n/)?.[0];
    if (!source) throw new Error("zoomWindow not found");
    const contents = { level: 0, getZoomLevel() { return this.level; }, setZoomLevel(level: number) { this.level = level; } };
    const win = { isDestroyed: () => false, webContents: contents };
    const publish = { hostZoomChanged: vi.fn() };
    const context = {
      BrowserWindow: { getFocusedWindow: () => win, getAllWindows: () => [win] },
      publish,
      zoomWindow: undefined as unknown as (change: number | "reset") => void,
    };
    vm.runInNewContext(`${source}; this.zoomWindow = zoomWindow;`, context);
    return { zoomWindow: context.zoomWindow, contents, publish };
  }

  it("缩放 Mosael 的界面,然后让内嵌视图按新的缩放重新摆(role 改完缩放不告诉任何人)", () => {
    const { zoomWindow, contents, publish } = loadZoomWindow();
    zoomWindow(0.5);
    zoomWindow(0.5);
    expect(contents.level).toBe(1);
    zoomWindow("reset");
    expect(contents.level).toBe(0);
    expect(publish.hostZoomChanged).toHaveBeenCalledTimes(3);
  });

  it("菜单里不再用 resetZoom / zoomIn / zoomOut 这几个 role", () => {
    expect(MAIN).not.toMatch(/role: "(resetZoom|zoomIn|zoomOut)"/);
    expect(MAIN).toMatch(/accelerator: "CmdOrCtrl\+Plus", click: \(\) => zoomWindow\(0\.5\)/);
  });
});
