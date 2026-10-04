/**
 * The single runtime contract for communication across Electron processes.
 *
 * Grouping by transport is intentional: `invoke` must have one `ipcMain.handle`,
 * `send` one `ipcMain.on`, and `event` flows from main to renderer.  Payloads
 * entering the privileged main process are decoded here before feature handlers
 * receive them.
 */
const IPC = Object.freeze({
  invoke: Object.freeze({
    checkUpdates: "mosael:check-updates",
    recordingStatus: "recording-permissions:status",
    recordingRequest: "recording-permissions:request",
    recordingOpenSettings: "recording-permissions:open-settings",
    getOpenAtLogin: "system:getOpenAtLogin",
    setOpenAtLogin: "system:setOpenAtLogin",
    customCssRead: "customCss:read",
    customCssPath: "customCss:path",
    customCssOpen: "customCss:open",
    customCssReveal: "customCss:reveal",
    dataExportDiagnostics: "data:exportDiagnostics",
    dataCreateBackup: "data:createBackup",
    dataApplyRestore: "data:applyRestore",
    publishLogin: "publish:login",
    publishOpenPage: "publish:openPage",
    publishInspect: "publish:inspect",
    publishNavigate: "publish:navigate",
    publishBack: "publish:back",
    publishForward: "publish:forward",
    publishReload: "publish:reload",
    publishHideView: "publish:hideView",
    publishPanelLayout: "publish:panelLayout",
    publishClosePanel: "publish:closePanel",
    publishPanelMuted: "publish:panelMuted",
    browserOpenLogin: "browser:openLogin",
    publishSignOut: "publish:signOut",
    browserClearProfile: "browser:clearProfile",
    // 浏览器会话顶栏的页面工具:只作用于前台那个内嵌视图(主进程自己认是哪个,渲染层不点名)。
    pageToolsCapture: "pageTools:capture",
    pageToolsRegionStart: "pageTools:regionStart",
    pageToolsRegionFinish: "pageTools:regionFinish",
    pageToolsVideos: "pageTools:videos",
    pageToolsImages: "pageTools:images",
    pageToolsFetchImages: "pageTools:fetchImages",
    pageToolsInset: "pageTools:inset",
  }),
  send: Object.freeze({
    titleOverlay: "mosael:title-overlay",
    systemStatus: "system:status",
    systemNotify: "system:notify",
    locale: "mosael:locale",
  }),
  event: Object.freeze({
    fullscreen: "mosael:fullscreen",
    openTasks: "mosael:open-tasks",
    deepLink: "mosael:deep-link",
    openFiles: "mosael:open-files",
    updateAvailable: "mosael:update-available",
    customCss: "mosael:custom-css",
    publishView: "publish:view",
    publishPanels: "publish:panels",
    browserFrame: "browser:frame",
  }),
});

function record(value, channel) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${channel}: payload must be an object`);
  }
  return value;
}

function requiredString(value, key, channel) {
  const text = typeof value[key] === "string" ? value[key].trim() : "";
  if (!text) throw new TypeError(`${channel}: ${key} must be a non-empty string`);
  return text;
}

function parseAuthToken(value, channel) {
  const payload = record(value, channel);
  const token = requiredString(payload, "token", channel);
  if (token.length > 16_384) throw new TypeError(`${channel}: token is too long`);
  return { token };
}

function parseRestoreStage(value) {
  const channel = IPC.invoke.dataApplyRestore;
  const payload = record(value, channel);
  const stageId = requiredString(payload, "stageId", channel);
  if (!/^[a-f0-9]{32}$/.test(stageId)) throw new TypeError(`${channel}: stageId is invalid`);
  return { stageId };
}

function parsePublishTarget(value, channel) {
  const payload = record(value, channel);
  return {
    accountId: requiredString(payload, "accountId", channel),
    platform: requiredString(payload, "platform", channel),
  };
}

function parseUrlRequest(value, channel) {
  const payload = record(value, channel);
  const url = requiredString(payload, "url", channel);
  if (!/^https?:\/\//i.test(url)) throw new TypeError(`${channel}: url must use http(s)`);
  return { url };
}

function parsePanelId(value) {
  const payload = record(value, IPC.invoke.publishClosePanel);
  return { id: requiredString(payload, "id", IPC.invoke.publishClosePanel) };
}

function parsePanelMuted(value) {
  const channel = IPC.invoke.publishPanelMuted;
  const payload = record(value, channel);
  if (typeof payload.muted !== "boolean") {
    throw new TypeError(`${channel}: muted must be a boolean`);
  }
  return { id: requiredString(payload, "id", channel), muted: payload.muted };
}

/** 悬浮面板的八个缩放手柄(四角 + 四边,罗盘方位)。 */
const PANEL_HANDLES = ["n", "ne", "e", "se", "s", "sw", "w", "nw"];

/**
 * 面板几何的一次改动:`{ x, y }` 是拖标题条挪位置;带 `handle` 的是拖手柄缩放,
 * `x/y/width/height` 是指针要的矩形(不带约束,主进程按比例与边界去夹)。
 *
 * **认不出的字段一律拒收**,不「半懂地执行」。渲染层由 vite 热更新,主进程只在启动时加载这份
 * 契约 —— 开发时两边不是同一版是常态。上一版解析器只挑自己认识的键、悄悄丢掉新加的 `handle`,
 * 于是新渲染层的「拖这个手柄缩放」被旧主进程当成「挪到这里 + 改宽」执行:拖角、拖边时整张卡片
 * 跟着平移(2026-10 用户在没重启的开发应用里撞到)。拒收让这种错位当场报错,一眼看得出是版本对不上。
 */
function parsePanelLayout(value) {
  const channel = IPC.invoke.publishPanelLayout;
  const payload = record(value, channel);
  const allowed = payload.handle === undefined ? ["x", "y"] : ["handle", "x", "y", "width", "height"];
  for (const key of Object.keys(payload)) {
    if (!allowed.includes(key)) throw new TypeError(`${channel}: unexpected field ${key}`);
  }
  const number = (key) => {
    if (typeof payload[key] !== "number" || !Number.isFinite(payload[key])) {
      throw new TypeError(`${channel}: ${key} must be a finite number`);
    }
    return payload[key];
  };
  if (payload.handle === undefined) return { x: number("x"), y: number("y") };
  if (!PANEL_HANDLES.includes(payload.handle)) {
    throw new TypeError(`${channel}: handle must be one of ${PANEL_HANDLES.join(", ")}`);
  }
  return { handle: payload.handle, x: number("x"), y: number("y"), width: number("width"), height: number("height") };
}

function parseBrowserLogin(value) {
  const channel = IPC.invoke.browserOpenLogin;
  const payload = record(value, channel);
  const partition = requiredString(payload, "partition", channel);
  if (!partition.startsWith("persist:pool-")) {
    throw new TypeError(`${channel}: partition must start with persist:pool-`);
  }
  const { url } = parseUrlRequest(payload, channel);
  return {
    partition,
    url,
    name: typeof payload.name === "string" ? payload.name.trim() : "",
    proxy: typeof payload.proxy === "string" && payload.proxy.trim() ? payload.proxy.trim() : null,
    // 视图还开着就接着用,不导航(见 AccountViewManager.openView)。
    resume: payload.resume === true,
  };
}

/** 清掉一个通用档案的登录数据。和 parseBrowserLogin 同一道闸:只认 persist:pool-* 分区。 */
function parseBrowserProfile(value) {
  const channel = IPC.invoke.browserClearProfile;
  const payload = record(value, channel);
  const partition = requiredString(payload, "partition", channel);
  if (!partition.startsWith("persist:pool-")) {
    throw new TypeError(`${channel}: partition must start with persist:pool-`);
  }
  return { partition };
}

/** 只认这几个键,多一个就拒(理由同 parsePanelLayout:渲染层热更新、主进程不重启时两边常常不是同一版)。 */
function onlyKeys(payload, allowed, channel) {
  for (const key of Object.keys(payload)) {
    if (!allowed.includes(key)) throw new TypeError(`${channel}: unexpected field ${key}`);
  }
}

function oneOf(payload, key, options, channel) {
  if (!options.includes(payload[key])) throw new TypeError(`${channel}: ${key} must be one of ${options.join(", ")}`);
  return payload[key];
}

/** 截屏:可见区域 / 整页长图(框选走 regionStart / regionFinish 两步)。 */
function parseCaptureMode(value) {
  const channel = IPC.invoke.pageToolsCapture;
  const payload = record(value, channel);
  onlyKeys(payload, ["mode"], channel);
  return { mode: oneOf(payload, "mode", ["visible", "full"], channel) };
}

/**
 * 框选的结果:冻结画面上的矩形,按画面的**比例**给(0–1)—— 显示尺寸只有渲染层知道,原图尺寸只有
 * 主进程知道,比例是两边都不用猜的那个量。`selection: null` 是取消。
 */
function parseRegionSelection(value) {
  const channel = IPC.invoke.pageToolsRegionFinish;
  const payload = record(value, channel);
  onlyKeys(payload, ["selection"], channel);
  if (payload.selection === null) return { selection: null };
  const rect = record(payload.selection, channel);
  onlyKeys(rect, ["x", "y", "width", "height"], channel);
  const fraction = (key, min) => {
    const n = rect[key];
    if (typeof n !== "number" || !Number.isFinite(n) || n < min || n > 1) {
      throw new TypeError(`${channel}: selection.${key} must be a number between ${min} and 1`);
    }
    return n;
  };
  const selection = { x: fraction("x", 0), y: fraction("y", 0), width: fraction("width", 0), height: fraction("height", 0) };
  if (selection.x + selection.width > 1.000001 || selection.y + selection.height > 1.000001) {
    throw new TypeError(`${channel}: selection must stay inside the frame`);
  }
  return { selection };
}

/** 取图:地址清单。主进程只取最近一次列图里出现过的地址(见 publish/pageImages.fetchImages)。 */
function parseImageUrls(value) {
  const channel = IPC.invoke.pageToolsFetchImages;
  const payload = record(value, channel);
  onlyKeys(payload, ["urls"], channel);
  const urls = payload.urls;
  if (!Array.isArray(urls) || urls.length === 0 || urls.length > 120) {
    throw new TypeError(`${channel}: urls must be a list of 1–120 addresses`);
  }
  for (const url of urls) {
    if (typeof url !== "string" || url.length > 4096 || !/^https?:\/\//i.test(url)) {
      throw new TypeError(`${channel}: every url must be an http(s) address`);
    }
  }
  return { urls };
}

/** 侧栏开合:前台视图右侧让出的像素宽。 */
function parseToolsInset(value) {
  const channel = IPC.invoke.pageToolsInset;
  const payload = record(value, channel);
  onlyKeys(payload, ["right"], channel);
  const right = payload.right;
  if (typeof right !== "number" || !Number.isFinite(right) || right < 0 || right > 4000) {
    throw new TypeError(`${channel}: right must be a number between 0 and 4000`);
  }
  return { right };
}

function parseTitleOverlay(value) {
  const channel = IPC.send.titleOverlay;
  const payload = record(value, channel);
  return {
    color: requiredString(payload, "color", channel),
    symbolColor: requiredString(payload, "symbolColor", channel),
  };
}

function parseSystemStatus(value) {
  const channel = IPC.send.systemStatus;
  const payload = record(value, channel);
  const runningJobs = payload.runningJobs;
  if (!Number.isInteger(runningJobs) || runningJobs < 0) {
    throw new TypeError(`${channel}: runningJobs must be a non-negative integer`);
  }
  const progress = payload.progress;
  if (progress !== undefined && progress !== null &&
      (typeof progress !== "number" || !Number.isFinite(progress) || progress < 0 || progress > 1)) {
    throw new TypeError(`${channel}: progress must be null or a number between 0 and 1`);
  }
  return { runningJobs, ...(progress === undefined ? {} : { progress }) };
}

function parseTaskNotice(value) {
  const channel = IPC.send.systemNotify;
  const payload = record(value, channel);
  return {
    title: requiredString(payload, "title", channel),
    body: typeof payload.body === "string" ? payload.body : "",
  };
}

/**
 * 渲染层的界面语言(`<html lang>` 上那个值,如 `en-US`)。主进程只认 zh / en,归一在
 * i18n.cjs 里做;这里只保证它是一个像样的语言标签,不是任意长的字符串。
 */
function parseLocale(value) {
  const channel = IPC.send.locale;
  const payload = record(value, channel);
  const locale = requiredString(payload, "locale", channel);
  if (!/^[A-Za-z]{2,8}([-_][A-Za-z0-9]{1,8})*$/.test(locale)) {
    throw new TypeError(`${channel}: locale must be a language tag`);
  }
  return { locale };
}

module.exports = {
  IPC,
  parseAuthToken,
  parseRestoreStage,
  parseBrowserLogin,
  parseBrowserProfile,
  parseCaptureMode,
  parseImageUrls,
  parseLocale,
  parsePanelId,
  parsePanelMuted,
  parsePanelLayout,
  parsePublishTarget,
  parseRegionSelection,
  parseSystemStatus,
  parseTaskNotice,
  parseTitleOverlay,
  parseToolsInset,
  parseUrlRequest,
};
