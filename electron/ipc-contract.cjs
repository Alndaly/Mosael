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
  parseLocale,
  parsePanelId,
  parsePanelMuted,
  parsePanelLayout,
  parsePublishTarget,
  parseSystemStatus,
  parseTaskNotice,
  parseTitleOverlay,
  parseUrlRequest,
};
