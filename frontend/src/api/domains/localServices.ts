/** 本机服务(ADR 0041):插件连接背后由宿主起停的那个进程 —— 配置、状态、日志、认目录、补装、本机发现。
 *
 * 建、改、起、停、认目录、补装都要部署管理员(后端 `ensure_deployment_admin`);`ensure`(工作台打开前请宿主先起好)
 * 只要是这个连接的主人。
 */
import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type LocalService = components["schemas"]["LocalServiceOut"];
export type LocalServiceState = LocalService["state"];
/** 建或改:没给的不动(`confirm_run_code` 只在换目录、换解释器时要)。 */
export type LocalServiceUpdate = Partial<components["schemas"]["LocalServiceUpdate"]>;
export type LocalServiceDetection = components["schemas"]["LocalServiceDetectOut"];
export type LocalServiceLogs = components["schemas"]["LocalServiceLogsOut"];
export type LocalServiceAddNodes = components["schemas"]["LocalServiceAddNodesOut"];
export type LocalServiceDiscovery = components["schemas"]["LocalServiceDiscoveryOut"];

const base = (instanceId: string) => `/api/plugins/instances/${instanceId}/local-service`;

/** 这个连接的本机服务;没用本机服务(连一台服务器)是 null。 */
export const getLocalService = (instanceId: string) => api<LocalService | null>(base(instanceId));
export const putLocalService = (instanceId: string, body: LocalServiceUpdate) =>
  api<LocalService>(base(instanceId), { method: "PUT", body: JSON.stringify(body) });
export const removeLocalService = (instanceId: string) => api(base(instanceId), { method: "DELETE" });
export const detectLocalService = (instanceId: string, directory: string, python: string) =>
  api<LocalServiceDetection>(`${base(instanceId)}/detect`, {
    method: "POST",
    body: JSON.stringify({ directory, python, confirm_run_code: true }),
  });
export const startLocalService = (instanceId: string) => api<LocalService>(`${base(instanceId)}/start`, { method: "POST" });
export const stopLocalService = (instanceId: string) => api<LocalService>(`${base(instanceId)}/stop`, { method: "POST" });
export const restartLocalService = (instanceId: string) =>
  api<LocalService>(`${base(instanceId)}/restart`, { method: "POST" });
/** 要用它了:停着就起,**等它就绪再回来**(第一次启动可能一两分钟)。没用本机服务的连接回 null。 */
export const ensureLocalService = (instanceId: string) =>
  api<LocalService | null>(`${base(instanceId)}/ensure`, { method: "POST" });
export const getLocalServiceLogs = (instanceId: string, limit = 400) =>
  api<LocalServiceLogs>(`${base(instanceId)}/logs?limit=${limit}`);
export const addLocalServiceNodes = (instanceId: string) =>
  api<LocalServiceAddNodes>(`${base(instanceId)}/add-nodes`, { method: "POST", body: JSON.stringify({ confirm: true }) });
/** 本机已经在跑的(插件知道去哪几个端口问)。只给部署管理员。 */
export const discoverLocalServices = (packageId: string) =>
  api<LocalServiceDiscovery>(`/api/plugins/${packageId}/local-services/discover`);
