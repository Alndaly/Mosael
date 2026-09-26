import type { QueryClient } from "@tanstack/react-query";

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
  ["workflow-field-options"],
  ["board-producers"],
  // 生成:插件生成连接是一家供应商,模型行是插件目录的缓存(ADR 0020)。
  ["generation-options"],
  ["provider-profiles"],
  ["provider-defaults"],
  ["provider-models"],
  ["capability-models"],
] as const;

export function invalidatePluginDependents(qc: QueryClient): void {
  for (const queryKey of PLUGIN_DEPENDENT_KEYS) void qc.invalidateQueries({ queryKey });
}
