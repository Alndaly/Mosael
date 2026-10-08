"use strict";

/**
 * 网页能拿到哪些权限。
 *
 * **Electron 不装处理器时一律放行**:通知、定位、摄像头、麦克风、读剪贴板、MIDI、拉起外部协议,网页一要就给,
 * 没有任何提示。内嵌浏览器(发布账号、浏览器池档案、RPA / 智能体会话、ComfyUI 工作台)里开的是任意第三方网页 ——
 * 智能体按任务去「读页面」「打开搜索结果」,碰到恶意网站是正常工作流;而 Mosael 为录旁白、录摄像头向系统要过
 * 麦克风和摄像头,授过之后网页的 getUserMedia 就再也没有提示。
 *
 * 所以两档,都是**默认拒绝**、只放名单里的:
 *
 * - **应用自己的页面**(主窗口、浮层视图;来源是应用自己的、而且是主框架):录音录像(`media`)、录屏
 *   (`display-capture`)、全屏、写剪贴板 —— 都是界面里真用到的(语音输入、录制、全屏预览、复制按钮)。
 *   外部协议只放 `mailto:`;http(s) 链接走 setWindowOpenHandler 那条交给系统浏览器的路,不经这里。
 * - **内嵌网页**(其余所有会话):只放全屏(看视频)和写剪贴板(网页上的「复制链接」)。读剪贴板、摄像头、麦克风、
 *   通知、定位、外部协议一律不给 —— 登录、发布、读页面都用不着它们;按 ⌘V 粘贴走的是 paste 事件,不要这个权限。
 *
 * 另有几样**只和「登录态留不留得住」有关**、不碰隐私也不碰设备的,拒了反而坏事,两档都放(按 Electron 44 实际会问的
 * 权限名逐个看过,见 web-permissions.test.ts 的 ELECTRON_44_PERMISSIONS):
 * - `persistent-storage`:磁盘紧张时别清这个站的数据。拒了,发布账号、浏览器池档案的 Cookie / 本地存储可能被回收,
 *   人得重新登录(维护者 main.log 里抖音创作者平台就在要它);Mosael 自己的登录令牌也在 localStorage 里。
 * - `storage-access` / `top-level-storage-access`(只给内嵌那一档):嵌在别的站里的登录框(第三方 iframe)要它自己的
 *   Cookie 时用的。Electron 本来就不拦第三方 Cookie,放行不多给什么;拒了,那种跨站登录框会当场说登录失败。
 * 后台同步、唤醒锁、本地网络访问、字体列表这些和登录态无关的照旧拒 —— 本地网络访问尤其不给:那是公网网页去探本机
 * 后端和局域网的口子。
 *
 * 内嵌那一档靠 `app.on("session-created")` 装在**每一个**新会话上(分区是谁建的、什么时候建的都不用记);
 * 应用那一档在 ready 之后单独装到默认会话上,覆盖掉前面那一档。
 */

/** 应用自己的页面能要的。 */
const APP_PERMISSIONS = new Set(["media", "display-capture", "fullscreen", "clipboard-sanitized-write", "persistent-storage"]);
/** 内嵌网页能要的。 */
const EMBEDDED_PERMISSIONS = new Set([
  "fullscreen",
  "clipboard-sanitized-write",
  "persistent-storage",
  "storage-access",
  "top-level-storage-access",
]);
/** 应用自己的页面能交给系统打开的外部协议(http(s) 不走这里)。 */
const APP_EXTERNAL_SCHEMES = new Set(["mailto:"]);

function schemeOf(raw) {
  try {
    return new URL(String(raw)).protocol;
  } catch {
    return "";
  }
}

function originOf(raw) {
  try {
    const url = new URL(String(raw));
    return url.protocol === "file:" ? "file://" : url.origin;
  } catch {
    return "";
  }
}

/**
 * 这一次要不要给。
 * @param {{ trusted: boolean, permission: string, externalURL?: string }} request
 *   trusted:请求来自应用自己的页面(主框架、应用自己的来源);内嵌网页一律 false。
 */
function permissionAllowed({ trusted, permission, externalURL }) {
  if (permission === "openExternal") return trusted && APP_EXTERNAL_SCHEMES.has(schemeOf(externalURL));
  return (trusted ? APP_PERMISSIONS : EMBEDDED_PERMISSIONS).has(permission);
}

/**
 * 装到一个会话上。`isAppUrl` 为 null 就是内嵌那一档(没有哪个来源算应用自己的)。
 * @param {Pick<Electron.Session, "setPermissionRequestHandler" | "setPermissionCheckHandler" | "setDevicePermissionHandler">} target
 * @param {{ isAppUrl: ((url: string) => boolean) | null, log?: (line: string) => void }} options
 */
function installPermissionPolicy(target, { isAppUrl, log = () => undefined }) {
  /** 请求来自应用自己的主框架吗。子框架(应用里嵌的第三方 iframe)不算。 */
  const trusted = (url, isMainFrame) => Boolean(isAppUrl) && isMainFrame !== false && isAppUrl(url);
  target.setPermissionRequestHandler((contents, permission, callback, details = {}) => {
    const url = details.requestingUrl || contents?.getURL?.() || "";
    const allowed = permissionAllowed({ trusted: trusted(url, details.isMainFrame), permission, externalURL: details.externalURL });
    // 只记来源和权限名:完整地址里可能带着令牌。
    if (!allowed) log(`denied ${permission} for ${originOf(url) || "unknown origin"}`);
    callback(allowed);
  });
  target.setPermissionCheckHandler((contents, permission, requestingOrigin, details = {}) => {
    const url = details.requestingUrl || contents?.getURL?.() || requestingOrigin || "";
    return permissionAllowed({ trusted: trusted(url, details.isMainFrame), permission });
  });
  // WebHID / WebSerial / WebUSB:谁都不给。
  target.setDevicePermissionHandler(() => false);
}

module.exports = { APP_PERMISSIONS, EMBEDDED_PERMISSIONS, APP_EXTERNAL_SCHEMES, installPermissionPolicy, permissionAllowed };
