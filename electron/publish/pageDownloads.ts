// 用户在内嵌浏览器里点的下载,存进素材库。路由器把「下好了」告诉渲染层(见 downloads.ts),渲染层带着
// 自己的会话来取:存进哪个服务器、哪个工作区、以谁的身份,都只有渲染层知道。
//
// 令牌只在这一次请求的头里用,不落盘、不进日志(和「创建备份」那条同一个做法,见 main.cjs dataCreateBackup)。
import { sharedViews } from "./accountViews";
import { discardDownload } from "./downloads";
import { provenanceFields, uploadDownload } from "./downloadUpload";
import { getLocale, t } from "../i18n.cjs";

export interface SaveDownloadRequest {
  id: string;
  server: string;
  token: string;
  workspaceId: string;
  projectId: string | null;
}

export interface SavedAsset {
  id: string;
  name: string;
  kind: string;
}

export async function saveDownload(request: SaveDownloadRequest): Promise<SavedAsset> {
  const file = sharedViews()?.downloads.take(request.id);
  if (!file) throw new Error(t("downloadErr_gone"));
  try {
    return await uploadDownload<SavedAsset>(
      `${request.server.replace(/\/+$/, "")}/api/assets/web-download`,
      { Authorization: `Bearer ${request.token}`, "Accept-Language": getLocale() },
      {
        workspace_id: request.workspaceId,
        ...(request.projectId ? { project_id: request.projectId } : {}),
        ...provenanceFields(file),
      },
      file,
    );
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(t("downloadErr_saveFailed", { name: file.name, reason }));
  } finally {
    discardDownload(file);
  }
}
