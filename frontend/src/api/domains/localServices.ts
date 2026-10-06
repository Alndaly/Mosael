/** 本机服务(ADR 0041):插件连接背后由宿主起停的那个进程 —— 配置、状态、日志、认目录、补装、本机发现,
 * 以及「让 Mosael 装」:安装计划、装(接着装、重建运行环境)、取消。
 *
 * 建、改、起、停、认目录、补装、看安装计划、装、取消都要部署管理员(后端 `ensure_deployment_admin`);`ensure`
 * (工作台打开前请宿主先起好)只要是这个连接的主人。
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
export type LocalServicePlan = components["schemas"]["LocalServicePlanOut"];
export type LocalServiceInstall = components["schemas"]["LocalServiceInstallOut"];
/** 看哪一份日志:服务自己说的话,还是「让 Mosael 装」那几步的输出。 */
export type LocalServiceLogSource = "service" | "install";

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
/** 还在用它(工作台、内嵌编辑器开着):闲置的钟从现在算。不替它起。 */
export const touchLocalService = (instanceId: string) => api(`${base(instanceId)}/touch`, { method: "POST" });
export const getLocalServiceLogs =(instanceId: string, limit = 400, source: LocalServiceLogSource = "service") =>
  api<LocalServiceLogs>(`${base(instanceId)}/logs?limit=${limit}&source=${source}`);
export const addLocalServiceNodes = (instanceId: string) =>
  api<LocalServiceAddNodes>(`${base(instanceId)}/add-nodes`, { method: "POST", body: JSON.stringify({ confirm: true }) });
/** 让 Mosael 装之前:这台机器能不能装、装哪种 PyTorch、要多少空间、分几步(接着装时哪几步已经做完)、从哪儿下。 */
export const getLocalServicePlan = (instanceId: string) => api<LocalServicePlan>(`${base(instanceId)}/plan`);
/** 装 / 接着装 / 重建运行环境(问过人了)。`flavour` 是安装计划里那种 PyTorch。马上回来,界面接着轮询。 */
export const installLocalService = (instanceId: string, flavour: string) =>
  api<LocalService>(`${base(instanceId)}/install`, {
    method: "POST",
    body: JSON.stringify({ confirm_run_code: true, flavour }),
  });
/** 取消正在装的:停在手上那一步,下次「接着装」从它开始。 */
export const cancelLocalServiceInstall = (instanceId: string) =>
  api<LocalService>(`${base(instanceId)}/install/cancel`, { method: "POST" });
export type LocalServiceModelFolders = components["schemas"]["LocalServiceModelFoldersOut"];
/** 共用的模型文件夹:每一处认成什么、在跑的话加载了没有、几个模型;卸载时保留下来、还没加进来的那几份。 */
export const getLocalServiceModelFolders = (instanceId: string) =>
  api<LocalServiceModelFolders>(`${base(instanceId)}/model-folders`);
/** 本机已经在跑的(插件知道去哪几个端口问)。只给部署管理员。 */
export const discoverLocalServices = (packageId: string) =>
  api<LocalServiceDiscovery>(`/api/plugins/${packageId}/local-services/discover`);
