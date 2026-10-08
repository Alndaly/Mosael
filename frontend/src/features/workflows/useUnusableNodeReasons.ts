import { useQueries } from "@tanstack/react-query";
import React from "react";

import { fetchUnusableNodeTypes, type WorkflowUnusableNode } from "@/api/client";

/**
 * 图里认不出的插件节点,各自**为什么**用不了 —— 后端说的真实原因(没装、没接连接、连接停用 / 缺凭据、
 * 工具没勾选……,见后端 plugins.nodes.why_unusable)。就绪清单、画布角标、检查器顶部读的是同一份。
 *
 * 此前三处只能说一句「没装、已停用或工具已不在」:节点面板只列我能用的插件节点,前端看不出是哪一种,
 * 而该去的地方各不相同。
 *
 * 按类型一条一条缓存:三处问的类型集合不同(清单问全图、检查器只问选中的那一个),按类型缓存才共用得上。
 * **请求却是一次**:同一拍里缺的那几个类型攒成一个请求问(接口本来就收多个 types,见 batchedReason)——
 * 此前一个类型一个请求,一张挂着二十个缺插件节点的图打开时并发二十个。
 * 不是插件节点的不问;问不到(还在路上、接口失败)就没有原因,调用方退回那句笼统的话。
 * 插件连接一变(装、卸、启停、勾选工具)这份缓存跟着失效(plugins/pluginCaches)。
 */
export function useUnusableNodeReasons(nodeTypes: readonly string[]): ReadonlyMap<string, WorkflowUnusableNode> {
  const types = React.useMemo(
    () => [...new Set(nodeTypes.filter((type) => type.startsWith("plugin.")))].sort(),
    [nodeTypes],
  );
  return useQueries({
    queries: types.map((type) => ({
      queryKey: ["workflow-node-unusable", type],
      queryFn: () => batchedReason(type),
      staleTime: 30_000,
    })),
    combine: reasonsOf,
  });
}

/** 这一拍里还在等回答的类型 → 等它的人。第一个进来的排一次 flush,同一拍里后来的搭同一个请求。 */
let waiting: Map<string, Array<{ resolve: (rows: WorkflowUnusableNode[]) => void; reject: (error: unknown) => void }>> | null =
  null;

/** 一个类型的回答(后端只回用不了的那几个:用得了的是空列表)。同一拍里的几个类型合成一个请求。 */
export function batchedReason(type: string): Promise<WorkflowUnusableNode[]> {
  return new Promise((resolve, reject) => {
    if (waiting === null) {
      waiting = new Map();
      setTimeout(flush, 0);
    }
    const queue = waiting.get(type) ?? [];
    queue.push({ resolve, reject });
    waiting.set(type, queue);
  });
}

async function flush(): Promise<void> {
  const batch = waiting;
  waiting = null;
  if (batch === null) return;
  try {
    const rows = await fetchUnusableNodeTypes([...batch.keys()].sort());
    for (const [type, queue] of batch) {
      const mine = rows.filter((row) => row.type === type);
      for (const one of queue) one.resolve(mine);
    }
  } catch (error) {
    for (const queue of batch.values()) for (const one of queue) one.reject(error);
  }
}

/** 模块级:combine 引用稳定,react-query 才只在结果变了的时候重算。修法是升级的那几个带着 `upgrade` 和连接(检查器给「去工作流库升级」)。 */
function reasonsOf(results: Array<{ data?: WorkflowUnusableNode[] }>): ReadonlyMap<string, WorkflowUnusableNode> {
  const reasons = new Map<string, WorkflowUnusableNode>();
  for (const result of results) for (const one of result.data ?? []) reasons.set(one.type, one);
  return reasons;
}
