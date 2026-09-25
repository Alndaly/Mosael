/**
 * 画布**正在编辑哪一层**:主流程,或者某个循环 / 子图节点的体,或者体里再套的那一层。
 *
 * 一层用一条路径表示:从主流程往里钻经过的容器节点 id,`[]` 就是主流程。编辑器只有一张图
 * (撤销、保存、自动同步都对着它),画布显示和编辑的是路径指到的那一层 —— 读用 graphAtScope,
 * 写用 withGraphAtScope 把新的那一层放回原处。
 *
 * 此前钻进循环体是另开一个编辑器:自己拷一份体图、自己一套连线 / 删除 / 添加逻辑、自己一个
 * React Flow 叠在主画布上面。两份状态、两套处理、两个同时听键盘的画布 —— 于是在体里按 Delete
 * 主画布也删(把正在编辑的那个循环节点删掉了),⌘V 粘进了看不见的主流程,撤销改了主图而体里的
 * 画面纹丝不动,体里套的循环则根本进不去。一张图 + 一条路径,这几件事就都不存在了。
 *
 * **哪些节点能钻进去由声明说了算**:节点类型里有一个 `type: "graph"` 的配置字段,它就是个容器,
 * 那个字段就是它的体。不认识具体节点类型。
 */
import type { WorkflowGraph } from "@/api/client";

type WNode = WorkflowGraph["nodes"][number];

export type ScopePath = readonly string[];

/** 只用到节点类型的配置声明。 */
export interface ScopeRegistry {
  get(type: string): { config?: Record<string, unknown> } | undefined;
}

const EMPTY_GRAPH: WorkflowGraph = { nodes: [], edges: [] };

/** 这种节点把体存在哪个配置字段里;不是容器就是 null。 */
export function bodyKey(registry: ScopeRegistry, nodeType: string): string | null {
  const config = registry.get(nodeType)?.config ?? {};
  for (const [key, spec] of Object.entries(config)) {
    if ((spec as { type?: unknown } | undefined)?.type === "graph") return key;
  }
  return null;
}

/** 容器节点的体。还没建(缺省、或者是添加节点时种下的空值)就是一张空图。 */
function bodyOf(node: WNode, key: string): WorkflowGraph {
  const raw = node.config?.[key] as WorkflowGraph | undefined;
  if (!raw || typeof raw !== "object" || !Array.isArray(raw.nodes)) return EMPTY_GRAPH;
  // 原样返回同一个对象:画布拿它和上一次比,换个新对象就是一次无谓的重建。
  return Array.isArray(raw.edges) ? raw : { ...raw, edges: [] };
}

/** 路径指到的那一层。路径上某一步不存在(节点被删、不再是容器)就是 null。 */
export function graphAtScope(root: WorkflowGraph, path: ScopePath, registry: ScopeRegistry): WorkflowGraph | null {
  let current = root;
  for (const id of path) {
    const node = current.nodes.find((one) => one.id === id);
    const key = node ? bodyKey(registry, node.type) : null;
    if (!node || !key) return null;
    current = bodyOf(node, key);
  }
  return current;
}

/** 路径最里面那个容器节点(主流程没有)。 */
export function scopeContainer(root: WorkflowGraph, path: ScopePath, registry: ScopeRegistry): WNode | null {
  if (path.length === 0) return null;
  const parent = graphAtScope(root, path.slice(0, -1), registry);
  return parent?.nodes.find((node) => node.id === path[path.length - 1]) ?? null;
}

/** 把 next 放回路径指到的那一层,返回新的整张图。路径无效时原样返回。 */
export function withGraphAtScope(
  root: WorkflowGraph,
  path: ScopePath,
  next: WorkflowGraph,
  registry: ScopeRegistry,
): WorkflowGraph {
  if (path.length === 0) return next;
  const [head, ...rest] = path;
  const node = root.nodes.find((one) => one.id === head);
  const key = node ? bodyKey(registry, node.type) : null;
  if (!node || !key) return root;
  const body = withGraphAtScope(bodyOf(node, key), rest, next, registry);
  return {
    ...root,
    nodes: root.nodes.map((one) => (one.id === head ? { ...one, config: { ...(one.config ?? {}), [key]: body } } : one)),
  };
}

/** 路径的存储形式(持久化、比较、当 React key 用都是它)。 */
export function scopeId(path: ScopePath): string {
  return JSON.stringify(path);
}

export function parseScopeId(id: string | null): ScopePath {
  if (!id) return [];
  try {
    const parsed: unknown = JSON.parse(id);
    return Array.isArray(parsed) && parsed.every((one) => typeof one === "string") ? parsed : [];
  } catch {
    return [];
  }
}

/** 这张图里所有能进去的层(不含主流程),给持久化的那份路径做校验。 */
export function scopeIds(root: WorkflowGraph, registry: ScopeRegistry): string[] {
  const out: string[] = [];
  const walk = (graph: WorkflowGraph, prefix: string[]) => {
    for (const node of graph.nodes) {
      const key = bodyKey(registry, node.type);
      if (!key) continue;
      const path = [...prefix, node.id];
      out.push(scopeId(path));
      walk(bodyOf(node, key), path);
    }
  };
  walk(root, []);
  return out;
}
