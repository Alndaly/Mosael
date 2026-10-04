/** 页面列表收起没有:记在这台电脑的这个界面里(只是个人习惯,不进后端)。 */
const COLLAPSED_KEY = "mosael.browserPages.collapsed";

export function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false; // 存储不可用(隐私模式之类):默认展开
  }
}

export function writeCollapsed(collapsed: boolean): void {
  try {
    if (collapsed) window.localStorage.setItem(COLLAPSED_KEY, "1");
    else window.localStorage.removeItem(COLLAPSED_KEY);
  } catch {
    // 记不住就算了,下次打开回到展开
  }
}

/** 拖动重排:把 `moved` 挪到 `target` 前面(往下拖时放到它后面 —— 落在谁身上就占谁的位置)。 */
export function moveBefore(ids: string[], moved: string, target: string): string[] {
  const from = ids.indexOf(moved);
  const to = ids.indexOf(target);
  if (from < 0 || to < 0 || from === to) return ids;
  const rest = ids.filter((id) => id !== moved);
  rest.splice(to, 0, moved);
  return rest;
}
