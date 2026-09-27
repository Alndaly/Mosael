/** 插件:装了哪些包、接了哪几个实例、它们的凭据与调用记录。
 *
 * 路径只写在这里 —— 界面调的是有名字、有类型的函数。此前插件页自己拼了十九条路径,
 * 改一个接口要去界面里找字符串,而拼错一个只会在运行时变成一次 404。
 */
import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type PluginPackage = components["schemas"]["PluginPackageOut"];
export type PluginInstance = components["schemas"]["PluginInstanceOut"];
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
export const previewPluginInstall = (url: string, advertisedVersion = "") =>
  api<PluginInstallPreview>("/api/plugins/install/preview", {
    method: "POST",
    body: JSON.stringify({ url, advertised_version: advertisedVersion }),
  });
export const installPlugin = (url: string, overwrite: boolean, advertisedVersion = "") =>
  api("/api/plugins/install", {
    method: "POST",
    body: JSON.stringify({ url, overwrite, advertised_version: advertisedVersion }),
  });
