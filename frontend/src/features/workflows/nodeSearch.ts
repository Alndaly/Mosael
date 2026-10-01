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
 *
 * **顺序是图序,和画布停在哪一层无关。** 此前当前这一层排最前:按 Enter 跳到别的层,条目当场按
 * 新的一层重排,而游标还记着下标 —— 指到了别的节点上,计数也错了,下一下 Enter 不是「下一个」。
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

/** 整张图里可搜的节点,按图序:每个节点后面紧跟着它体里的那些(深度优先)。 */
export function nodeSearchTargets(root: WorkflowGraph, registry: Registry): NodeSearchTarget[] {
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
  return out;
}

/** `path` 是不是 `layer` 本身或它里面的某一层。 */
function isWithin(path: ScopePath, layer: ScopePath): boolean {
  return path.length >= layer.length && layer.every((id, index) => path[index] === id);
}

/**
 * 命中集换成当前这一层画布上的节点 id。这一层的命中圈它自己;**更深处的命中圈在通往它的那个容器上**
 * (同 analyze.issuesAtLayer 的折法)—— 站在主流程上搜体里的节点,画布上总得看出「在这个循环里」。
 * 更外层、别的分支里的命中这一层画不出来,在列表里。
 */
export function highlightAtLayer(
  hit: CanvasSearchHighlight | null,
  targets: readonly NodeSearchTarget[],
  current: ScopePath,
): CanvasSearchHighlight | null {
  if (!hit) return null;
  const ids = new Set<string>();
  let activeId: string | null = null;
  for (const one of targets) {
    if (!hit.ids.has(one.id) || !isWithin(one.path, current)) continue;
    const here = one.path.length === current.length;
    ids.add(here ? one.nodeId : one.path[current.length]!);
    if (here && one.id === hit.activeId) activeId = one.nodeId;
  }
  return { ids, activeId };
}
