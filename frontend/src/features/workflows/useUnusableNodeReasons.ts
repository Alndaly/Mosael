import { useQueries } from "@tanstack/react-query";
import React from "react";

import { fetchUnusableNodeTypes } from "@/api/client";

/**
 * 图里认不出的插件节点,各自**为什么**用不了 —— 后端说的真实原因(没装、没接连接、连接停用 / 缺凭据、
 * 工具没勾选……,见后端 plugins.nodes.why_unusable)。就绪清单、画布角标、检查器顶部读的是同一份。
 *
 * 此前三处只能说一句「没装、已停用或工具已不在」:节点面板只列我能用的插件节点,前端看不出是哪一种,
 * 而该去的地方各不相同。
 *
 * 按类型一条一条缓存:三处问的类型集合不同(清单问全图、检查器只问选中的那一个),按类型缓存才共用得上。
 * 不是插件节点的不问;问不到(还在路上、接口失败)就没有原因,调用方退回那句笼统的话。
 */
export function useUnusableNodeReasons(nodeTypes: readonly string[]): ReadonlyMap<string, string> {
  const types = React.useMemo(
    () => [...new Set(nodeTypes.filter((type) => type.startsWith("plugin.")))].sort(),
    [nodeTypes],
  );
  return useQueries({
    queries: types.map((type) => ({
      queryKey: ["workflow-node-unusable", type],
      queryFn: () => fetchUnusableNodeTypes([type]),
      staleTime: 30_000,
    })),
    combine: reasonsOf,
  });
}

/** 模块级:combine 引用稳定,react-query 才只在结果变了的时候重算。 */
function reasonsOf(results: Array<{ data?: Array<{ type: string; reason: string }> }>): ReadonlyMap<string, string> {
  const reasons = new Map<string, string>();
  for (const result of results) for (const one of result.data ?? []) reasons.set(one.type, one.reason);
  return reasons;
}
