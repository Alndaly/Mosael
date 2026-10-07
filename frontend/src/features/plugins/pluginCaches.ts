import type { QueryClient } from "@tanstack/react-query";

import { refreshPluginInstance } from "@/api/client";
import { generationKeys, providerKeys } from "@/api/queryKeys";

/**
 * **跟着插件连接走的那些缓存**:装、卸、建连接、改配置、启停、授权、刷新之后都要失效。
 *
 * 插件不只出现在插件页。一条生成插件连接(ComfyUI)就是 AI 工作台里的一家供应商和一串模型,暴露出来的
 * 工具是工作流的节点、画板上一格的能力 / 空格子的生成器、节点表单里「用哪个连接」的下拉。此前插件页只失效了自己那几份,
 * 于是在插件页启用 ComfyUI、点「刷新模型」之后回到 AI 工作台,模型选择器还是旧的那一份,要等一分钟
 * (默认 staleTime)或者刷新整页才出现 —— 用户以为刷新没成功。
 *
 * 前缀匹配(见 api/queryKeys):键写到最短,每一份细分的缓存都能匹配到。
 */
export const PLUGIN_DEPENDENT_KEYS = [
  ["plugins"],
  ["plugin-models"],
  // 工作流 / 画板:插件工具是节点和格子的能力;「用哪个连接」的下拉从插件连接列出。
  ["workflow-node-types"],
  // 插件节点为什么用不了(没接、停用、工具没勾选):连接一变原因就变,不该等 30 秒的 staleTime。
  ["workflow-node-unusable"],
  ["workflow-field-options"],
  ["board-producers"],
  // 生成:插件生成连接是一家供应商,模型行是插件目录的缓存(ADR 0020)。
  generationKeys.options(),
  providerKeys.profiles(),
  providerKeys.defaults(),
  providerKeys.models(),
  providerKeys.capabilityModels(),
] as const;

export function invalidatePluginDependents(qc: QueryClient): void {
  for (const queryKey of PLUGIN_DEPENDENT_KEYS) void qc.invalidateQueries({ queryKey });
}

/** 正在重拉目录的连接:同一时刻几处都要它重拉(工作台存了一张、工作台关了、工作流库回来)时只拉一次。 */
const refreshing = new Map<string, Promise<void>>();

/**
 * **这个连接上的工作流变了**(存了精简表单、改了名、在工作台里存了一张):先让后端重拉这个连接的目录,再让依赖它的
 * 查询重问。精简表单、工作流的名字都住在那张图里,AI 工作台的「引擎参数」、画板的提示词面板、工作流节点读的是后端按
 * 连接存着的那份目录(ADR 0020)—— 只让界面重问,拿到的还是旧的。
 *
 * 同一个连接正在拉的,后来的那一处接着等同一次,不再叫一遍(插件一次要把那台机器上的每张工作流拉一遍)。拉不成也照样让
 * 界面重问:目录留着上一份,原因在插件页上。
 */
export function refreshConnectionCatalog(qc: QueryClient, instanceId: string): Promise<void> {
  const running = refreshing.get(instanceId);
  if (running) return running;
  const done = Promise.resolve()
    .then(() => refreshPluginInstance(instanceId))
    .then(() => undefined, () => undefined)
    .finally(() => {
      refreshing.delete(instanceId);
      invalidatePluginDependents(qc);
    });
  refreshing.set(instanceId, done);
  return done;
}
