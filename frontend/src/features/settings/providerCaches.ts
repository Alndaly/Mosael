import type { QueryClient } from "@tanstack/react-query";

import { generationKeys, providerKeys } from "@/api/queryKeys";

/**
 * **跟着供应商连接走的那些缓存**:建、改、删、启停连接,授权 / 退出登录,增删启停模型之后都要失效。
 *
 * 连接不只出现在设置页。它的模型是默认模型那几格的候选(capability-models / provider-defaults),也是 AI 工作台、
 * 画板生成选择器里的那一串(generation-options)。此前三处各失效各的:模型列表那处带上了生成选择器,
 * 连接列表和授权弹窗没带 —— 停掉一个连接、授权完一个订阅计划之后,生成选择器还是旧的,要刷新整页才对。
 *
 * 前缀匹配(见 api/queryKeys):键写到最短,每一份细分的缓存(某个连接的模型、某种能力的选项)都能匹配到。
 * 插件那一侧的同类清单见 features/plugins/pluginCaches。
 */
export const PROVIDER_DEPENDENT_KEYS = [
  providerKeys.profiles(),
  providerKeys.models(),
  providerKeys.defaults(),
  providerKeys.capabilityModels(),
  generationKeys.options(),
] as const;

export function invalidateProviderDependents(qc: QueryClient): Promise<void> {
  return Promise.all(PROVIDER_DEPENDENT_KEYS.map((queryKey) => qc.invalidateQueries({ queryKey }))).then(() => undefined);
}
