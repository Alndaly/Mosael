import type { WorkflowGraph } from "@/api/client";
import type { CanvasSearchEntry, CanvasSearchHighlight } from "@/components/app/CanvasNodeSearch";
import { bodyKey, scopeId, type ScopePath, type ScopeRegistry } from "@/features/workflows/scope";

/**
 * 工作流的「查找节点」搜**整张图**:主流程,以及每个循环体 / 子图(连同体里再套的那一层)里的节点。
 *
 * 此前只搜画布正在显示的那一层 —— 站在主流程上找不到循环体里的「合成口播」,得先猜它在哪个
 * 循环里、钻进去再搜。节点 id 也不参与匹配,而运行报错、就绪清单、智能体说的都是 id。
 *
 * 体里的 id 和主流程是两套命名空间(见 scope.ts),同一个 id 可以在两层各有一个,所以条目的 id
 * 是「层 + 节点」一起编出来的;画布上的高亮只认当前这一层的节点 id,由 highlightAtLayer 换回去。
 */
export interface NodeSearchTarget extends CanvasSearchEntry {
  path: ScopePath;
  nodeId: string;
}

interface Registry extends ScopeRegistry {
  get(type: string): { label?: string; config?: Record<string, unknown>; body_scope?: Record<string, string[]> } | undefined;
}

export function nodeSearchEntryId(path: ScopePath, nodeId: string): string {
  return scopeId([...path, nodeId]);
}

/** 整张图里可搜的节点。当前这一层排最前 —— 空查询时先列出眼前的这些,和此前一致。 */
export function nodeSearchTargets(root: WorkflowGraph, registry: Registry, current: ScopePath): NodeSearchTarget[] {
  const out: NodeSearchTarget[] = [];
  const walk = (graph: WorkflowGraph, path: string[], inside: string) => {
    for (const node of graph.nodes) {
      const label = registry.get(node.type)?.label ?? node.type;
      const title = node.name || label;
      out.push({
        id: nodeSearchEntryId(path, node.id),
        path,
        nodeId: node.id,
        title,
        //: 体里的节点在小字里说清在哪一层(「逐镜生成 › 合成口播」同一种写法,见 analyze 的 nodeName)。
        subtitle: inside ? `${label} · ${inside}` : label,
        text: [node.type, node.id],
      });
      const key = bodyKey(registry, node.type);
      const body = key ? (node.config?.[key] as WorkflowGraph | undefined) : undefined;
      if (body && typeof body === "object" && Array.isArray(body.nodes)) {
        walk({ ...body, edges: body.edges ?? [] }, [...path, node.id], inside ? `${inside} › ${title}` : title);
      }
    }
  };
  walk(root, [], "");
  const here = scopeId(current);
  return [...out.filter((one) => scopeId(one.path) === here), ...out.filter((one) => scopeId(one.path) !== here)];
}

/** 命中集换成当前这一层画布上的节点 id:别的层里的命中这一层画不出来。 */
export function highlightAtLayer(
  hit: CanvasSearchHighlight | null,
  targets: readonly NodeSearchTarget[],
  current: ScopePath,
): CanvasSearchHighlight | null {
  if (!hit) return null;
  const here = scopeId(current);
  const onLayer = targets.filter((one) => scopeId(one.path) === here);
  const ids = new Set(onLayer.filter((one) => hit.ids.has(one.id)).map((one) => one.nodeId));
  const active = onLayer.find((one) => one.id === hit.activeId);
  return { ids, activeId: active?.nodeId ?? null };
}
