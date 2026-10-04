/**
 * 渲染层经 `ipcRenderer.invoke` 调主进程失败时,给人看的那句话。
 *
 * Electron 把主进程抛的错包成「Error invoking remote method 'pageTools:capture': Error: …」再交给渲染层,
 * 界面上原样显示就是一串英文前缀加报错类型名(用户截图里就是「没做成:Error invoking remote method
 * 'pageTools:i…'」)。这里统一剥掉:去掉 Electron 的前缀、报错类型名和堆栈,留下主进程自己那句话(主进程的报错
 * 本来就按界面语言翻好了,页面工具的原因码 `page-tools: no_page` 也照样留着给渲染层认)。
 *
 * **主进程里没有这个处理器**(「No handler registered for …」)说的是:主进程还是旧的 —— 开发时 watch 重编了
 * bundle、渲染层热更新成了新代码,而正在跑的主进程是启动时加载的那一版。这时说要重启。
 *
 * 映射在调 IPC 的这一层统一做:preload 里每个 invoke 都过 `humanIpcError`(ipc-errors.test.ts 守着),
 * 不靠每个按钮各自记得。
 */
const { MESSAGES, normalizeLocale } = require("./i18n.cjs");

const REMOTE_PREFIX = /^Error invoking remote method '[^']*':\s*/;
const ERROR_NAME = /^(?:[A-Z][A-Za-z]*Error|Error):\s*/;
const NO_HANDLER = /No handler registered for '/;

/**
 * 按界面语言取一句(preload 里没有主进程那份当前语言,语言由调用方从页面上读)。
 * @param {"ipcErr_mainOutdated" | "ipcErr_failed"} key
 * @param {string | undefined} locale
 */
function say(key, locale) {
  const entry = MESSAGES[key];
  return entry[normalizeLocale(locale)] || entry.zh;
}

/**
 * @param {unknown} error invoke 拒绝时给的东西
 * @param {string} [locale] 界面语言(`<html lang>`)
 * @returns {Error}
 */
function humanIpcError(error, locale) {
  const raw = String((error && typeof error === "object" && "message" in error ? error.message : error) ?? "");
  if (NO_HANDLER.test(raw)) return new Error(say("ipcErr_mainOutdated", locale));
  const firstLine = raw.split("\n").find((line) => line.trim() && !/^\s+at\s/.test(line)) ?? "";
  const message = firstLine.replace(REMOTE_PREFIX, "").replace(ERROR_NAME, "").trim();
  return new Error(message || say("ipcErr_failed", locale));
}

module.exports = { humanIpcError };
