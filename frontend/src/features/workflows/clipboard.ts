/**
 * 节点剪贴板的纯图变换:把复制下来的一组节点粘进一张图。UI 无关、可单测。
 *
 * 一组节点之间有两种联系:边(控制边 / 数据边),以及配置里的 `{{id.output}}` 引用。
 * 粘贴要给每个节点换新 id,**两者都得跟着换** —— 只重连边、不改引用的话,粘出来的
 * 「模板」仍然引用原件里的「大模型」:它不在自己的上游,运行时拿到的是另一条支路的输出
 * (或者因为原件不在祖先里而取不到),而画布上看着完全正常。
 *
 * 组外的引用(`{{start.topic}}`)原样保留:那是这组节点对外部的依赖,复制不改变它。
 * 内嵌子图的作用域(循环体 / 子图体 / 它们的 output)里的引用指向**体内**的节点,
 * 和外层 id 是两套命名空间,不能拿外层的换名表去改。代码字段也不改:代码不插值,里面的
 * `{{…}}` 是代码的字面文字,不是引用(见 analyze.isCodeConfig)—— 改了等于悄悄改了用户的代码。
 */
import type { WorkflowGraph } from "@/api/client";
import { isCodeConfig, isNestedScopeConfig, type RegistryLike } from "@/features/workflows/analyze";
import { rewriteRefs } from "@/features/workflows/collapse";

type WNode = WorkflowGraph["nodes"][number];
type WEdge = WorkflowGraph["edges"][number];

export interface NodeClip {
  nodes: WNode[];
  edges: WEdge[];
  /** 选中节点对**外**的连线(恰好一端在选区):Cmd+Shift+V 带连线粘贴时,把仍在图里的那端重接上。 */
  external?: WEdge[];
}

/** 每次粘贴相对原件往右下错开多少 —— 连按 ⌘V 时一层层错开,不叠成一摞。 */
export const PASTE_OFFSET = 48;

/** 当前图里没用过的节点 id,和「添加节点」同一种形状:`llm-1`、`llm-2`…… */
function idAllocator(graph: WorkflowGraph): (type: string) => string {
  const used = new Set(graph.nodes.map((node) => node.id));
  return (type) => {
    const base = type.replace(/[_.]/g, "-");
    let index = 1;
    while (used.has(`${base}-${index}`)) index += 1;
    const id = `${base}-${index}`;
    used.add(id);
    return id;
  };
}

/** 一个节点的配置里,把指向组内节点的引用换成新 id。 */
function remapConfig(node: WNode, idMap: Map<string, string>, registry: RegistryLike): WNode["config"] {
  const config = node.config ?? {};
  return Object.fromEntries(
    Object.entries(config).map(([key, value]) => [
      key,
      isNestedScopeConfig(registry, node.type, key) || isCodeConfig(registry, node.type, key)
        ? value
        : rewriteRefs(value, (source) => idMap.get(source) ?? null),
    ]),
  );
}

/**
 * 把 clip 粘进 graph。start 唯一,不复制;一个能粘的都没有时返回 null。
 *
 * 返回的 `clip` 是**位置已经错开一格**的剪贴板,供下一次粘贴继续往右下错。
 */
export function pasteNodes(
  graph: WorkflowGraph,
  clip: NodeClip,
  registry: RegistryLike,
  /** 黏贴落点(画布坐标):给了就把整组节点的**左上角**挪到那,没给就按老习惯从原位置右下错开。 */
  at?: { x: number; y: number } | null,
  /** 带连线粘贴(Cmd+Shift+V):把选中节点对外的连线也重接上(另一端仍在图里的才接)。 */
  withConnections?: boolean,
): { graph: WorkflowGraph; pastedIds: string[]; clip: NodeClip } | null {
  const freshId = idAllocator(graph);
  const idMap = new Map<string, string>();
  for (const node of clip.nodes) {
    if (node.type === "start") continue;
    idMap.set(node.id, freshId(node.type));
  }
  if (idMap.size === 0) return null;
  // 成组节点的左上角(粘进多个时当一整个搬):给了落点就把这个角对齐到鼠标,相对位置原样保留。
  const minX = Math.min(...clip.nodes.map((node) => node.position?.x ?? 0));
  const minY = Math.min(...clip.nodes.map((node) => node.position?.y ?? 0));
  const dx = at ? at.x - minX : PASTE_OFFSET;
  const dy = at ? at.y - minY : PASTE_OFFSET;
  const shift = (node: WNode): WNode["position"] => ({
    x: (node.position?.x ?? 0) + dx,
    y: (node.position?.y ?? 0) + dy,
  });
  const newNodes = clip.nodes
    .filter((node) => idMap.has(node.id))
    .map((node) => ({
      ...structuredClone(node),
      id: idMap.get(node.id)!,
      position: shift(node),
      config: remapConfig(structuredClone(node), idMap, registry),
    }));
  const newEdges = clip.edges
    .filter((edge) => idMap.has(edge.source) && idMap.has(edge.target))
    .map((edge) => {
      const source = idMap.get(edge.source)!;
      const target = idMap.get(edge.target)!;
      const id =
        edge.kind === "data"
          ? `d-${source}-${edge.source_output}-${target}-${edge.target_input}`
          : `e-${source}${edge.source_handle ? `-${edge.source_handle}` : ""}-${target}`;
      return { ...structuredClone(edge), id, source, target };
    });
  // 带连线粘贴:把选中节点对外的连线重接上 —— 粘上的那端换新 id,另一端保持原节点(仍在图里才接)。
  // 节点的入参声明/清空随 structuredClone 一起带过来了,重接连线即恢复「由边供值」。
  if (withConnections && clip.external) {
    for (const edge of clip.external) {
      const source = idMap.has(edge.source) ? idMap.get(edge.source)! : edge.source;
      const target = idMap.has(edge.target) ? idMap.get(edge.target)! : edge.target;
      // 对外的那端若已不在图里(比如连同它一起删了),这条线无处可接,跳过。
      if (!idMap.has(edge.source) && !graph.nodes.some((node) => node.id === edge.source)) continue;
      if (!idMap.has(edge.target) && !graph.nodes.some((node) => node.id === edge.target)) continue;
      const id =
        edge.kind === "data"
          ? `d-${source}-${edge.source_output}-${target}-${edge.target_input}`
          : `e-${source}${edge.source_handle ? `-${edge.source_handle}` : ""}-${target}`;
      if (graph.edges.some((one) => one.id === id) || newEdges.some((one) => one.id === id)) continue;
      newEdges.push({ ...structuredClone(edge), id, source, target });
    }
  }
  return {
    graph: { ...graph, nodes: [...graph.nodes, ...newNodes], edges: [...graph.edges, ...newEdges] },
    pastedIds: newNodes.map((node) => node.id),
    clip: structuredClone({
      nodes: clip.nodes.map((node) => ({ ...node, position: shift(node) })),
      edges: clip.edges,
      external: clip.external,
    }),
  };
}
