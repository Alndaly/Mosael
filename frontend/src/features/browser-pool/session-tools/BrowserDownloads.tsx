import React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { assetKeys } from "@/api/queryKeys";
import { API_BASE, getAuthToken } from "@/api/transport";
import { BrowserToolsWorkspace } from "@/app/browserToolsWorkspace";
import { useI18n } from "@/app/preferences";

import { announceDownload, progressText, saveFinishedDownload, type DownloadNotice } from "./downloadActions";
import { showSavedAsset, type Notice } from "./useToolNotice";

/**
 * 内嵌浏览器里点的下载:**不弹系统保存框,下完直接存进素材库。**
 *
 * 主进程接管下载、存到临时目录,下好了告诉这里(见 electron/publish/downloads.ts);这里用界面自己的服务器
 * 和会话把它存进当前工作区。挂在应用最外层而不是顶栏里:下载可能在用户收起内嵌浏览器之后才下完,那时顶栏
 * 已经不在了,文件照样要存。提示在顶栏挂着时说在顶栏里(网页盖住了窗口其余部分),否则用应用的 toast。
 *
 * 浏览器自动化里触发的下载不经过这里:那一路由执行器交给后端,记在触发它的那次运行上。
 */
export function BrowserDownloads() {
  const tools = window.mosaelPageTools;
  if (!tools?.onDownload) return null;
  return <DownloadSaver tools={tools} />;
}

function DownloadSaver({ tools }: { tools: NonNullable<Window["mosaelPageTools"]> }) {
  const t = useI18n();
  const qc = useQueryClient();
  const { workspaceId } = React.useContext(BrowserToolsWorkspace);
  // 回调里要最新的工作区,但不该因为它变了就重新订阅(那会漏掉中间到的通知)。
  const workspace = React.useRef(workspaceId);
  React.useEffect(() => {
    workspace.current = workspaceId;
  }, [workspaceId]);

  React.useEffect(() => {
    const tell = (id: string, notice: Notice) => {
      if (announceDownload(notice)) {
        toast.dismiss(id);
        return;
      }
      const options = { id, ...(notice.action ? { action: { label: notice.action.label, onClick: notice.action.run } } : {}) };
      if (notice.tone === "busy") toast.loading(notice.text, options);
      else if (notice.tone === "done") toast.success(notice.text, options);
      else toast.error(notice.text, options);
    };
    const handle = async (download: DownloadNotice) => {
      if (download.state === "progress") {
        tell(download.id, { tone: "busy", text: progressText(download, t) });
        return;
      }
      if (download.state === "failed") {
        tell(download.id, { tone: "error", text: t("browserToolsDownloadFailed").replace("{reason}", download.error ?? "") });
        return;
      }
      tell(download.id, { tone: "busy", text: t("browserToolsFileSaving").replace("{name}", download.name) });
      try {
        const asset = await saveFinishedDownload(
          download,
          { workspaceId: workspace.current, server: API_BASE, token: getAuthToken(), save: tools.saveDownload },
          t,
        );
        void qc.invalidateQueries({ queryKey: assetKeys.everywhere() });
        tell(download.id, {
          tone: "done",
          text: t("browserToolsFileSaved").replace("{name}", asset.name),
          action: { label: t("browserToolsView"), run: () => showSavedAsset(asset.id) },
        });
      } catch (error) {
        tell(download.id, { tone: "error", text: (error as Error)?.message || String(error) });
      }
    };
    return tools.onDownload((download) => void handle(download));
  }, [qc, t, tools]);

  return null;
}
