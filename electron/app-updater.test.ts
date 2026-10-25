import { EventEmitter } from "node:events";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it, vi } from "vitest";

const realRequire = createRequire(import.meta.url);
const { compareVersions, createAppUpdater } = realRequire("./app-updater.cjs");

type FakeUpdater = EventEmitter & {
  autoDownload: boolean;
  autoInstallOnAppQuit: boolean;
  allowPrerelease: boolean;
  setFeedURL: ReturnType<typeof vi.fn>;
  checkForUpdates: ReturnType<typeof vi.fn>;
  downloadUpdate: ReturnType<typeof vi.fn>;
  quitAndInstall: ReturnType<typeof vi.fn>;
};

function updater(): FakeUpdater {
  const one = new EventEmitter() as FakeUpdater;
  one.autoDownload = true;
  one.autoInstallOnAppQuit = true;
  one.allowPrerelease = true;
  one.setFeedURL = vi.fn();
  one.checkForUpdates = vi.fn(async () => ({ updateInfo: { version: "2.2.2" } }));
  one.downloadUpdate = vi.fn(async () => {
    one.emit("download-progress", { percent: 50, transferred: 50, total: 100 });
    one.emit("update-downloaded", { version: "2.2.2" });
    return "/tmp/update.zip";
  });
  one.quitAndInstall = vi.fn();
  return one;
}

function setup({ dev = false, runningJobs = 0 }: { dev?: boolean; runningJobs?: number } = {}) {
  const events: Array<{ kind: string; info: Record<string, unknown> }> = [];
  const onInstall = vi.fn();
  const updaterInstance = updater();
  const controller = createAppUpdater({
    app: { getVersion: () => "2.2.1" },
    autoUpdater: dev ? null : updaterInstance,
    isDev: dev,
    emit: (kind: string, info: Record<string, unknown>) => events.push({ kind, info }),
    log: vi.fn(),
    net: {
      fetch: vi.fn(async () => ({
        ok: true,
        json: async () => ({ tag_name: "v2.2.2", html_url: "https://github.com/Alndaly/Mosael/releases/tag/v2.2.2" }),
      })),
    },
    setTimeout: vi.fn(),
    setInterval: vi.fn(),
    getRunningJobs: () => runningJobs,
    onInstall,
  });
  return { controller, updater: updaterInstance, events, onInstall };
}

describe("应用内更新", () => {
  it("版本比较按数字段,不按字符串", () => {
    expect(compareVersions("2.2.10", "2.2.2")).toBe(1);
    expect(compareVersions("2.2.1", "2.2.1")).toBe(0);
    expect(compareVersions("2.2.0", "2.2.1")).toBe(-1);
  });

  it("打包版:发现更新 → 下载进度 → 下载完成 → 静默安装并重启", async () => {
    const { controller, updater, events, onInstall } = setup();
    expect(updater.setFeedURL).toHaveBeenCalledWith({ provider: "github", owner: "Alndaly", repo: "Mosael" });
    expect(updater.autoDownload).toBe(false);
    expect(updater.autoInstallOnAppQuit).toBe(false);
    expect(updater.allowPrerelease).toBe(false);

    const checked = await controller.check();
    expect(checked).toMatchObject({ latest: "2.2.2", hasUpdate: true, supportsAutoInstall: true, phase: "available" });

    const downloaded = await controller.download();
    expect(updater.downloadUpdate).toHaveBeenCalledTimes(1);
    expect(downloaded.phase).toBe("downloaded");
    expect(events.map((event) => event.kind)).toEqual(["progress", "progress", "progress"]);
    expect(events[0].info.percent).toBe(0);
    expect(events[1].info.percent).toBe(50);
    expect(events[2].info.percent).toBe(100);

    const installing = controller.install();
    expect(installing.phase).toBe("installing");
    expect(updater.quitAndInstall).toHaveBeenCalledWith(true, true);
    expect(onInstall).toHaveBeenCalledTimes(1);
  });

  it("同一轮下载不重复发起", async () => {
    const { controller, updater } = setup();
    await controller.check();
    const pending = Promise.withResolvers<void>();
    updater.downloadUpdate.mockImplementation(() => pending.promise);
    const first = controller.download();
    await controller.download();
    expect(updater.downloadUpdate).toHaveBeenCalledTimes(1);
    pending.resolve();
    await first;
  });

  it("没下载完成不能安装", async () => {
    const { controller, updater } = setup();
    await controller.check();
    expect(controller.install().error).toBe("update_notDownloaded");
    expect(updater.quitAndInstall).not.toHaveBeenCalled();
  });
  it("有任务在跑时先不重启", async () => {
    const { controller, updater, onInstall } = setup({ runningJobs: 1 });
    await controller.check();
    await controller.download();
    expect(controller.install()).toMatchObject({ phase: "deferred", error: "update_jobsRunning" });
    expect(updater.quitAndInstall).not.toHaveBeenCalled();
    expect(onInstall).not.toHaveBeenCalled();
  });

  it("开发模式只读检查,不给应用内安装", async () => {
    const { controller, events } = setup({ dev: true });
    const checked = await controller.check();
    expect(checked).toMatchObject({ supportsAutoInstall: false, hasUpdate: true });
    expect((await controller.download()).error).toBe("update_installUnsupported");
    expect(events).toHaveLength(0);
  });
});
describe("更新元数据", () => {
  it("从最终 ZIP / NSIS 生成带 sha512 的 latest-mac.yml / latest.yml", () => {
    const dir = mkdtempSync(join(tmpdir(), "mosael-update-metadata-"));
    const mac = join(dir, "Mosael-2.2.2-mac-signed.zip");
    const windows = join(dir, "Mosael Setup 2.2.2.exe");
    writeFileSync(mac, "zip");
    writeFileSync(windows, "exe");
    const root = fileURLToPath(new URL("..", import.meta.url));
    execFileSync(process.execPath, [
      join(root, "scripts", "write-update-metadata.mjs"),
      "--version", "2.2.2",
      "--mac", mac,
      "--windows", windows,
      "--out", dir,
    ], { cwd: root, stdio: "pipe" });

    const macYml = readFileSync(join(dir, "latest-mac.yml"), "utf8");
    const winYml = readFileSync(join(dir, "latest.yml"), "utf8");
    const macSha = createHash("sha512").update("zip").digest("base64");
    const winSha = createHash("sha512").update("exe").digest("base64");
    expect(macYml).toContain("path: Mosael-2.2.2-mac-signed.zip");
    expect(macYml).toContain(`sha512: ${macSha}`);
    expect(macYml).toContain("size: 3");
    expect(winYml).toContain("path: Mosael.Setup.2.2.2.exe");
    expect(winYml).toContain(`sha512: ${winSha}`);
    expect(winYml).toContain("size: 3");
  });
});
