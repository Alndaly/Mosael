import { ensureLocalService, getLocalService } from "@/api/client";

/**
 * 打开工作台之前(ADR 0041 §2「工作台打开前先请宿主起好」):这个连接背后是宿主起停的本机服务,就先请宿主
 * 起好 —— 停着就起、等它就绪(第一次启动可能要一两分钟)。真要起的时候先叫一声 `onStarting`,界面摆「启动中」。
 *
 * 没用本机服务、已经在跑:马上回来。问状态问不到(网页版连不上、旧后端没有这个接口)也照常往下开 —— 开不开得了由那一步说;
 * 起不来照抛,原因是宿主说的那一句(端口被占、等不到就绪……)。
 */
export async function readyLocalService(instanceId: string, onStarting: () => void): Promise<void> {
  let state: string | null = null;
  try {
    state = (await getLocalService(instanceId))?.state ?? null;
  } catch {
    return;
  }
  if (state === null || state === "running") return;
  onStarting();
  await ensureLocalService(instanceId);
}
