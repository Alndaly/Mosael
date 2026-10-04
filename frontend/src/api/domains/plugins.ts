/** 插件:装了哪些包、接了哪几个实例、它们的凭据与调用记录。
 *
 * 路径只写在这里 —— 界面调的是有名字、有类型的函数。此前插件页自己拼了十九条路径,
 * 改一个接口要去界面里找字符串,而拼错一个只会在运行时变成一次 404。
 */
import type { components } from "@/api/generated/schema";
import type { Job } from "@/api/domains/jobs";
import { API_BASE, api, getAuthToken } from "@/api/transport";

export type PluginPackage = components["schemas"]["PluginPackageOut"];
export type PluginInstance = components["schemas"]["PluginInstanceOut"];
/** 连接往外连走哪条路:跟随 Mosael / 直连 / 走它自己的代理(见 backend domain/plugins/egress)。 */
export type PluginNetwork = components["schemas"]["PluginNetworkOut"];
export type PluginField = components["schemas"]["PluginFieldOut"];
export type PluginCapabilityStatus = components["schemas"]["PluginCapabilityStatusOut"];
export type PluginToolState = components["schemas"]["PluginToolStateOut"];
export type PluginTool = components["schemas"]["PluginToolOut"];
export type PluginInvocation = components["schemas"]["PluginInvocationOut"];
export type PluginPermissionGrant = components["schemas"]["PluginPermissionGrantOut"];
export type PluginCredential = components["schemas"]["PluginCredentialOut"];
export type PluginMarketEntry = components["schemas"]["PluginMarketEntry"];
export type PluginMarketListing = components["schemas"]["PluginMarketOut"];
export type PluginInstallPreview = components["schemas"]["PluginInstallPreview"];
export type PluginProvidedModel = components["schemas"]["PluginProvidedModelOut"];
/** 模型库(ADR 0034):认领 model_library 的连接上的模型文件、工作流缺的模型、下载走哪条路。 */
export type ModelLibrary = components["schemas"]["ModelLibraryOut"];
export type ModelFile = components["schemas"]["ModelFileOut"];
export type MissingModel = components["schemas"]["MissingModelOut"];
export type ModelDetail = components["schemas"]["ModelDetailOut"];
export type ModelResolved = components["schemas"]["ModelResolveOut"];

export const listPluginPackages = () => api<PluginPackage[]>("/api/plugins");
export const pluginDir = () => api<{ path: string }>("/api/plugins/dir");
export const rescanPlugins = () => api<PluginPackage[]>("/api/plugins/scan", { method: "POST" });
export const removePluginPackage = (packageId: string) => api(`/api/plugins/${packageId}`, { method: "DELETE" });

export const createPluginInstance = (packageId: string, body: Record<string, unknown>) =>
  api<PluginInstance>(`/api/plugins/${packageId}/instances`, { method: "POST", body: JSON.stringify(body) });
export const updatePluginInstance = (instanceId: string, body: Record<string, unknown>) =>
  api<PluginInstance>(`/api/plugins/instances/${instanceId}`, { method: "PATCH", body: JSON.stringify(body) });
export const removePluginInstance = (instanceId: string) =>
  api(`/api/plugins/instances/${instanceId}`, { method: "DELETE" });
export const refreshPluginInstance = (instanceId: string) =>
  api<PluginInstance>(`/api/plugins/instances/${instanceId}/refresh`, { method: "POST" });
/** 替宿主做生成的连接**提供的模型**(缓存的那一份;要最新的先 refresh)。 */
export const listPluginInstanceModels = (instanceId: string) =>
  api<PluginProvidedModel[]>(`/api/plugins/instances/${instanceId}/models`);
export const setPluginCapabilities = (instanceId: string, body: Record<string, unknown>) =>
  api<PluginInstance>(`/api/plugins/instances/${instanceId}/capabilities`, { method: "PATCH", body: JSON.stringify(body) });

export const listPluginPermissions = (instanceId: string) =>
  api<PluginPermissionGrant[]>(`/api/plugins/instances/${instanceId}/permissions`);
export const setPluginPermissions = (instanceId: string, body: Record<string, unknown>) =>
  api<PluginPermissionGrant[]>(`/api/plugins/instances/${instanceId}/permissions`, { method: "PATCH", body: JSON.stringify(body) });

export const startPluginOauth = (instanceId: string) =>
  api<{ authorize_url: string }>(`/api/plugins/instances/${instanceId}/oauth`);
export const finishPluginOauth = (instanceId: string, code: string) =>
  api(`/api/plugins/instances/${instanceId}/oauth`, { method: "POST", body: JSON.stringify({ code }) });

/** 一条连接要填的凭据。`filled` 说的是「后端手里有」,`value` 永远是空或掩码 —— 密钥不回传。 */
export type PluginCredentialRow = { key: string; label: string; help: string; secret: boolean; filled: boolean; value: string };
export const listPluginCredentials = (instanceId: string) =>
  api<PluginCredentialRow[]>(`/api/plugins/instances/${instanceId}/credentials`);
export const savePluginCredentials = (instanceId: string, values: Record<string, string>) =>
  api<PluginCredentialRow[]>(`/api/plugins/instances/${instanceId}/credentials`, { method: "PATCH", body: JSON.stringify({ values }) });

export const invokePluginTool = (instanceId: string, tool: string, body: Record<string, unknown>) =>
  api<PluginInvocation>(`/api/plugins/instances/${instanceId}/tools/${tool}/invoke`, { method: "POST", body: JSON.stringify(body) });
export const listPluginInvocations = (instanceId: string) =>
  api<PluginInvocation[]>(`/api/plugins/invocations?instance_id=${encodeURIComponent(instanceId)}`);
export const clearPluginInvocations = (instanceId: string) =>
  api(`/api/plugins/invocations?instance_id=${encodeURIComponent(instanceId)}`, { method: "DELETE" });
export const removePluginInvocation = (invocationId: string) =>
  api(`/api/plugins/invocations/${invocationId}`, { method: "DELETE" });

export const listPluginMarket = () => api<PluginMarketListing>("/api/plugins/market");
/**
 * `advertisedVersion`:从市场点的时候,索引给这一条写的版本(从链接装时留空)。有它,后端才认得出
 * 「从市场更新、而包里其实不比装着的新」—— 那时不装、也不报「已更新」,而是说新版本还没发布。
 */
export const previewPluginInstall = (url: string, advertisedVersion = "", sha256 = "") =>
  api<PluginInstallPreview>("/api/plugins/install/preview", {
    method: "POST",
    body: JSON.stringify({ url, advertised_version: advertisedVersion, sha256 }),
  });
/** `sha256`:市场索引给这个包写的摘要,后端下载后核对,对不上不装。从链接装时留空。 */
export const installPlugin = (url: string, overwrite: boolean, advertisedVersion = "", sha256 = "") =>
  api("/api/plugins/install", {
    method: "POST",
    body: JSON.stringify({ url, overwrite, advertised_version: advertisedVersion, sha256 }),
  });


// --- 模型库(ADR 0034) ---------------------------------------------------------

/** 现问插件:这个连接上的全部模型文件(第一次要读文件头,几百个文件要几秒)。 */
export const getModelLibrary = (instanceId: string) =>
  api<ModelLibrary>(`/api/plugins/instances/${instanceId}/model-library`);

export const getModelDetail = (instanceId: string, folder: string, name: string) =>
  api<ModelDetail>(`/api/plugins/instances/${instanceId}/model-library/detail?${new URLSearchParams({ folder, name })}`);

/** 一个链接(HuggingFace 文件、Civitai 页面或下载链接、ModelScope 的模型页或文件、别的直链)指的是哪个文件。 */
export const resolveModelLink = (instanceId: string, url: string) =>
  api<ModelResolved>(`/api/plugins/instances/${instanceId}/model-library/resolve`, {
    method: "POST",
    body: JSON.stringify({ url }),
  });

/** 下到这个连接的那台服务器上:一个后台任务(进度、取消都在任务上)。 */
export const startModelDownload = (
  instanceId: string,
  body: { workspace_id: string; url: string; folder: string; filename: string },
) => api<Job>(`/api/plugins/instances/${instanceId}/model-library/downloads`, { method: "POST", body: JSON.stringify(body) });

/** 预览图地址。`<img>` 带不了请求头,凭据走 `?token=`(和素材的图同一条旁路)。 */
export function modelPreviewUrl(instanceId: string, folder: string, name: string): string {
  const params = new URLSearchParams({ folder, name });
  const token = getAuthToken();
  if (token) params.set("token", token);
  return `${API_BASE}/api/plugins/instances/${instanceId}/model-library/preview?${params}`;
}
