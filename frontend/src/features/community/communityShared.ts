/** 社区账号状态的缓存键。设置页、分享面板、发布弹窗读的是同一份:在一处连上 / 断开,别处跟着变。 */
export const COMMUNITY_STATUS_KEY = ["community-status"] as const;

/**
 * 在系统浏览器里打开一个网页(设备授权页、社区上的条目)。
 *
 * 走的是应用里所有外链的那一条路:`window.open` → Electron 的 setWindowOpenHandler → `shell.openExternal`
 * (见 electron/main.cjs)。不在应用里开一个没有地址栏的新窗口 —— 用户要在自己的浏览器里登录社区。
 */
export function openInBrowser(url: string): void {
  window.open(url, "_blank", "noopener");
}

/** 把一句带占位符的文案填好(`{name}` → 值)。 */
export function fill(template: string, values: Record<string, string | number>): string {
  return Object.entries(values).reduce((text, [key, value]) => text.split(`{${key}}`).join(String(value)), template);
}
