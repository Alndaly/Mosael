import type { MessageKey } from "@/app/messages";

import type { Notice } from "./useToolNotice";

/** 主进程报来的一份下载(见 electron/publish/downloads.ts 的 DownloadNotice)。 */
export type DownloadNotice = Parameters<Parameters<NonNullable<Window["mosaelPageTools"]>["onDownload"]>[0]>[0];
type SaveDownload = NonNullable<Window["mosaelPageTools"]>["saveDownload"];

/**
 * 下载的提示往哪儿说。内嵌浏览器亮着时网页盖住了窗口其余部分,只有顶栏看得见 —— 顶栏的页面工具挂着就交给它;
 * 没挂着(用户已经回到应用)就由调用方用应用的 toast 说。
 *
 * 一个模块级的小广播,不放 context:说话的(BrowserDownloads)挂在应用最外层,听的(顶栏工具区)跟着内嵌
 * 视图来去,两边不在同一棵子树里。
 */
const listeners = new Set<(notice: Notice) => void>();

export function listenDownloadNotices(listener: (notice: Notice) => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** 交给顶栏说;没人听就返回 false。 */
export function announceDownload(notice: Notice): boolean {
  if (!listeners.size) return false;
  for (const listener of listeners) listener(notice);
  return true;
}

/** 下载中的那句话:知道总长就带百分比。 */
export function progressText(notice: DownloadNotice, t: (key: MessageKey) => string): string {
  if (notice.totalBytes > 0) {
    const percent = Math.min(100, Math.floor((notice.receivedBytes / notice.totalBytes) * 100));
    return t("browserToolsFileDownloading").replace("{name}", notice.name).replace("{p}", String(percent));
  }
  return t("browserToolsFileDownloadingUnknown").replace("{name}", notice.name);
}

/**
 * 把下好的那份存进当前工作区。存到哪个服务器、以谁的身份:用的就是这个界面自己连着的那个服务器和会话。
 * 没进工作区(登录页、连接中)就不存 —— 抛出那句话,文件由主进程过一阵删掉。
 */
export async function saveFinishedDownload(
  notice: DownloadNotice,
  host: { workspaceId: string | null; server: string; token: string | null; save: SaveDownload },
  t: (key: MessageKey) => string,
): Promise<{ id: string; name: string; kind: string }> {
  if (!host.workspaceId || !host.token) {
    throw new Error(t("browserToolsFileNoWorkspace").replace("{name}", notice.name));
  }
  return host.save({ id: notice.id, server: host.server, token: host.token, workspaceId: host.workspaceId, projectId: null });
}
