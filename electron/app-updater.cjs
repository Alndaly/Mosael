/**
 * 应用更新:GitHub Releases 的版本检查 + electron-updater 的应用内下载/安装。
 *
 * 只读检查在开发模式也保留(旧行为);应用内安装只在打包版开放。
 * 用工厂隔离 electron-updater 的 EventEmitter 和进程生命周期,测试可以注入假的 updater。
 */
const UPDATE_OWNER = "Alndaly";
const UPDATE_REPO = "Mosael";
const UPDATE_RELEASES = `https://github.com/${UPDATE_OWNER}/${UPDATE_REPO}/releases`;
const UPDATE_API = `https://api.github.com/repos/${UPDATE_OWNER}/${UPDATE_REPO}/releases/latest`;
const MANUAL_DOWNLOAD_URL = "https://pan.baidu.com/s/5n5TXJoBkkF61BOyzFqgnjg";

function compareVersions(a, b) {
  const parse = (value) => String(value).replace(/^v/i, "").split(".").map((part) => parseInt(part, 10) || 0);
  const [pa, pb] = [parse(a), parse(b)];
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff) return diff > 0 ? 1 : -1;
  }
  return 0;
}

function createAppUpdater({ app, autoUpdater, emit, log, net, isDev, setTimeout: later, setInterval: every, getRunningJobs = () => 0, onInstall = () => {}, getFeedUrl = async () => "" }) {
  const enabled = !isDev && Boolean(autoUpdater);
  const current = app.getVersion();
  let latest = "";
  let phase = enabled ? "idle" : "unsupported";
  let percent = 0;
  let transferred = 0;
  let total = 0;
  let error = "";
  let announced = "";
  let selectedFeed = "";
  let fallback = false;
  let downloadPromise = null;

  const supportsAutoInstall = enabled;
  const url = () => (latest ? `${UPDATE_RELEASES}/tag/v${latest}` : UPDATE_RELEASES);
  const githubFeed = () => autoUpdater.setFeedURL({ provider: "github", owner: UPDATE_OWNER, repo: UPDATE_REPO });
  const info = (extra = {}) => ({
    current,
    latest,
    hasUpdate: compareVersions(latest, current) > 0,
    supportsAutoInstall,
    phase,
    percent,
    transferred,
    total,
    error,
    url: url(),
    manualUrl: MANUAL_DOWNLOAD_URL,
    source: fallback ? "github-fallback" : selectedFeed ? "r2" : "github",
    ...extra,
  });
  const emitProgress = (extra = {}) => emit("progress", info(extra));
  const prepareFeed = async () => {
    const next = (await getFeedUrl()).trim();
    if (next !== selectedFeed) {
      selectedFeed = next;
      fallback = false;
    }
    if (fallback || !selectedFeed) {
      githubFeed();
    } else {
      autoUpdater.setFeedURL({ provider: "generic", url: selectedFeed });
    }
    return selectedFeed;
  };
  const withFallback = async (work) => {
    try {
      return await work();
    } catch (cause) {
      if (!selectedFeed || fallback) throw cause;
      fallback = true;
      latest = "";
      phase = "available";
      githubFeed();
      log("update-feed-fallback", cause);
      return work();
    }
  };
  const emitAvailable = () => emit("available", info());

  if (enabled) {
    autoUpdater.autoDownload = false;
    autoUpdater.autoInstallOnAppQuit = false;
    autoUpdater.allowPrerelease = false;
    githubFeed();
    autoUpdater.on("download-progress", (progress) => {
      phase = "downloading";
      percent = Math.max(0, Math.min(100, Math.round(Number(progress.percent) || 0)));
      transferred = Number(progress.transferred) || 0;
      total = Number(progress.total) || 0;
      emitProgress();
    });
    autoUpdater.on("update-downloaded", () => {
      phase = "downloaded";
      percent = 100;
      emitProgress();
    });
    autoUpdater.on("error", (cause) => {
      phase = "error";
      error = String(cause?.message || cause || "update download failed");
      emitProgress();
    });
  }

  async function legacyCheck() {
    const response = await net.fetch(UPDATE_API, {
      headers: { Accept: "application/vnd.github+json", "User-Agent": "mosael-updater" },
    });
    if (!response.ok) throw new Error(`GitHub ${response.status}`);
    const release = await response.json();
    latest = String(release.tag_name || "").replace(/^v/i, "");
    if (!latest) throw new Error("update_noTag");
    return info({ url: release.html_url || url() });
  }

  async function check({ announce = false } = {}) {
    error = "";
    if (!enabled) {
      const result = await legacyCheck();
      phase = result.hasUpdate ? "available" : "up-to-date";
      if (announce && result.hasUpdate && latest !== announced) {
        announced = latest;
        emitAvailable();
      }
      return result;
    }
    await prepareFeed();
    const result = await withFallback(() => autoUpdater.checkForUpdates());
    const next = String(result?.updateInfo?.version || "").replace(/^v/i, "");
    if (!next) throw new Error("update_noTag");
    const changed = latest !== next;
    latest = next;
    if (changed && phase !== "downloaded") phase = "available";
    if (!info().hasUpdate) phase = "up-to-date";
    if (announce && info().hasUpdate && latest !== announced && phase !== "downloading" && phase !== "downloaded") {
      announced = latest;
      emitAvailable();
    }
    return info();
  }

  async function download() {
    if (!enabled) return info({ error: "update_installUnsupported" });
    if (phase === "downloaded") return info();
    if (downloadPromise) return info();
    if (!latest || !info().hasUpdate) await check();
    if (!info().hasUpdate) return info();
    phase = "downloading";
    percent = 0;
    error = "";
    emitProgress();
    downloadPromise = withFallback(() => autoUpdater.downloadUpdate()).finally(() => {
      downloadPromise = null;
    });
    await downloadPromise;
    return info();
  }

  function install() {
    if (!enabled) return info({ error: "update_installUnsupported" });
    if (phase !== "downloaded" && phase !== "deferred") return info({ error: "update_notDownloaded" });
    if (getRunningJobs() > 0) {
      phase = "deferred";
      emitProgress({ error: "update_jobsRunning" });
      return info({ error: "update_jobsRunning" });
    }
    // macOS 的 Squirrel 可能在 before-quit 之前关窗;先退出常驻模式,
    // 否则 residency 的 close 拦截会把这次安装改写成隐藏窗口。
    onInstall();
    autoUpdater.quitAndInstall(true, true);
    return info({ phase: "installing" });
  }

  function start() {
    if (!enabled) return;
    const announce = () => {
      check({ announce: true }).catch((cause) => log("update-check-failed", cause));
    };
    later(announce, 5000);
    every(announce, 24 * 60 * 60 * 1000);
  }

  return { check, download, install, start, info };
}

module.exports = { compareVersions, createAppUpdater };
