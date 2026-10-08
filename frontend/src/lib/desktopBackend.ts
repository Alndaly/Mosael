/**
 * 桌面版的内置后端连崩几次之后,主进程会认输、不再自己重拉(见 electron/backend-lifecycle.cjs)。那之后界面上的
 * 「重试」只是再发一遍请求 —— 后端都没了,怎么点都一样。所以「重试」先请主进程真的重拉它:正跑着就立刻回,认输了就
 * 拉起来、等它就绪再回。网页版、连团队服务器时没有这座桥,什么都不做。
 */
/** 有这座桥吗(桌面版、主进程是带 backend:retry 的那一版)。没有时「重试」照旧当场重取,不多等一拍。 */
export function canReviveDesktopBackend(): boolean {
  return typeof window !== "undefined" && typeof window.mosaelDesktop?.backend?.retry === "function";
}

export async function reviveDesktopBackend(): Promise<void> {
  try {
    await window.mosaelDesktop?.backend?.retry();
  } catch {
    // 重拉没成:照常重试,界面会接着说连不上。
  }
}
