/** 「框选 → 折叠为子图」的纯图变换(参考 ComfyUI 的 subgraph)。UI 无关、可单测:
 *  输入完整 graph + 选中节点 id,输出把选区收进一个 subgraph 节点后的新 graph。
 *
 *  本 app 的数据流有两条:节点间 `{{id.key}}` 字符串引用(主),与数据边(kind="data",
 *  source_output→target_input)。折叠必须**同时**重写两者,跨越选区边界的引用才不会断:
 *   - 入边界(外→内):外层源 u 被选区引用 → 子图开一个同名输入 inputs[u]="{{u}}"(整份输出,
 *     interpolate 整串引用保留原类型),内部 `{{u.k}}` 改写成 `{{input.u.k}}`;入边界数据边改成
 *     目标节点 config 上的 `{{input.u.so}}` 模板。
 *   - 出边界(内→外):子图 output 留空 → 运行时输出整份子上下文 {内部id: 输出};外层 `{{v.k}}`
 *     改写成 `{{sg.output.v.k}}`;出边界数据边改成外层目标 config 上的 `{{sg.output.v.so}}` 模板。
 *  排序仍靠边:入/出边界边收缩成 u→sg / sg→w(去重、保留入边的 source_handle 做条件路由)。
 *
 *  会拒绝的情况:选区含 start(子图体不能有 start);选区非凸(中间隔着未选中的节点,收缩后成环);
 *  出边界从**条件节点**的分支拉出(子图只有单一 output,无法再暴露 true/false 分支,会丢语义)。
 *
 *  **「谁依赖谁」和后端同一个算法**(domain/workflows.reference_dependencies):连线,加上**这一层
 *  作用域里**的 `{{…}}` 引用。两处此前都和后端不一样:
 *   - 凸性只看连线 —— 只靠引用串起来的 a ← w ← c 选 {a,c} 照样折叠,存盘时后端才报环路;
 *   - 引用改写钻进了循环 / 子图节点的 body/output/condition —— 那里的 `{{template-1.text}}` 指的是
 *     **体内**的 template-1(体的节点 id 自成一套,和外层撞名是常态),却被当成外层节点改写成
 *     `{{input.template-1.text}}`,折叠完的循环安静地读错了值。
 */
import type { WorkflowGraph } from "../../api/client";
import { extractRefs, isNestedScopeConfig, type RegistryLike } from "@/features/workflows/analyze";

type Graph = WorkflowGraph;
type WNode = Graph["nodes"][number];
type WEdge = Graph["edges"][number];

const VAR_RE = /\{\{\s*([\w.-]+)\s*\}\}/g;

export type CollapseReason = "empty" | "start" | "not-convex" | "condition-branch";
export interface CollapseOk {
  ok: true;
  graph: Graph;
  subgraphId: string;
}
export interface CollapseErr {
  ok: false;
  reason: CollapseReason;
}
export type CollapseResult = CollapseOk | CollapseErr;

/** 深度改写一个 config 值里的所有 `{{id...}}` 引用:remap(leadingId) 返回新的前导段(可含点,
 *  如 "input.llm-1"),返回 null 则保持原样。非字符串/数组/对象原样递归。 */
export function rewriteRefs(value: unknown, remap: (leadingId: string) => string | null): unknown {
  if (typeof value === "string") {
    if (!value.includes("{{")) return value;
    return value.replace(VAR_RE, (whole, inner: string) => {
      const parts = inner.split(".");
      const mapped = remap(parts[0]);
      if (mapped == null) return whole;
      parts[0] = mapped;
      return `{{${parts.join(".")}}}`;
    });
  }
  if (Array.isArray(value)) return value.map((v) => rewriteRefs(v, remap));
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) out[k] = rewriteRefs(v, remap);
    return out;
  }
  return value;
}

/** 只改写**这一层作用域**里的引用:内嵌子图节点的 body/output/condition 属于体自己,原样保留。 */
function rewriteOuterRefs(
  node: WNode,
  registry: RegistryLike,
  remap: (leadingId: string) => string | null,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(node.config ?? {})) {
    out[key] = isNestedScopeConfig(registry, node.type, key) ? value : rewriteRefs(value, remap);
  }
  return out;
}

/** 这个节点在**这一层**引用了哪些节点 id(与后端 reference_dependencies 同一口径)。 */
function outerRefSources(node: WNode, registry: RegistryLike): string[] {
  return Object.entries(node.config ?? {})
    .filter(([key]) => !isNestedScopeConfig(registry, node.type, key))
    .flatMap(([, value]) => extractRefs(value).map(({ sourceId }) => sourceId));
}

/** 生成一个当前 graph 里没用过的节点 id(deterministic:扫已用后缀,不用随机/时间)。 */
function freshId(graph: Graph, base: string): string {
  const used = new Set(graph.nodes.map((n) => n.id));
  if (!used.has(base)) return base;
  let i = 1;
  while (used.has(`${base}-${i}`)) i += 1;
  return `${base}-${i}`;
}

function averagePosition(nodes: WNode[]): { x: number; y: number } {
  const pts = nodes.map((n) => n.position ?? { x: 0, y: 0 });
  if (pts.length === 0) return { x: 0, y: 0 };
  const sum = pts.reduce((acc, p) => ({ x: acc.x + p.x, y: acc.y + p.y }), { x: 0, y: 0 });
  return { x: Math.round(sum.x / pts.length), y: Math.round(sum.y / pts.length) };
}

/** 把选区收缩成一个代表点 sg 后,图是否仍无环(凸性检查)。有环 → 选区非凸,不能折叠。
 *  依赖 = 连线 + 这一层的 `{{…}}` 引用(引用即依赖,后端排序和查环都这么算)。 */
function contractionHasCycle(graph: Graph, selected: Set<string>, sgId: string, registry: RegistryLike): boolean {
  const rep = (id: string) => (selected.has(id) ? sgId : id);
  const adj = new Map<string, Set<string>>();
  const nodes = new Set<string>([sgId]);
  for (const n of graph.nodes) if (!selected.has(n.id)) nodes.add(n.id);
  for (const id of nodes) adj.set(id, new Set());
  const ids = new Set(graph.nodes.map((n) => n.id));
  const dependencies: Array<[string, string]> = [
    ...graph.edges.map((e): [string, string] => [e.source, e.target]),
    ...graph.nodes.flatMap((n) =>
      outerRefSources(n, registry)
        .filter((source) => ids.has(source) && source !== n.id)
        .map((source): [string, string] => [source, n.id]),
    ),
  ];
  for (const [source, target] of dependencies) {
    const a = rep(source);
    const b = rep(target);
    if (a === b) continue; // 内部边/自环,不影响外层排序
    if (!adj.has(a) || !adj.has(b)) continue;
    adj.get(a)!.add(b);
  }
  // Kahn 拓扑:能全部出队则无环。
  const indeg = new Map<string, number>();
  for (const id of nodes) indeg.set(id, 0);
  for (const [, tos] of adj) for (const to of tos) indeg.set(to, (indeg.get(to) ?? 0) + 1);
  const queue = [...nodes].filter((id) => (indeg.get(id) ?? 0) === 0);
  let visited = 0;
  while (queue.length) {
    const cur = queue.shift()!;
    visited += 1;
    for (const to of adj.get(cur) ?? []) {
      indeg.set(to, (indeg.get(to) ?? 0) - 1);
      if ((indeg.get(to) ?? 0) === 0) queue.push(to);
    }
  }
  return visited !== nodes.size;
}

/** 纯变换:把 selected 收进一个 subgraph 节点。name 是新节点的显示名(调用方按界面语言给);opts.id 便于测试固定。
 *  registry 说明哪些节点带内嵌子图(body_scope)—— 它们的体属于自己的作用域。 */
export function collapseToSubgraph(
  graph: Graph,
  selected: string[],
  registry: RegistryLike,
  opts: { name: string; id?: string },
): CollapseResult {
  const S = new Set(selected.filter((id) => graph.nodes.some((n) => n.id === id)));
  if (S.size === 0) return { ok: false, reason: "empty" };
  const selNodes = graph.nodes.filter((n) => S.has(n.id));
  if (selNodes.some((n) => n.type === "start")) return { ok: false, reason: "start" };

  const outerIds = new Set(graph.nodes.map((n) => n.id));
  const typeById = new Map(graph.nodes.map((n) => [n.id, n.type]));
  const sgId = opts.id ?? freshId(graph, "subgraph");

  // 1. 边分区
  const internalEdges: WEdge[] = [];
  const inEdges: WEdge[] = []; // 外→内
  const outEdges: WEdge[] = []; // 内→外
  const externalEdges: WEdge[] = []; // 外→外
  for (const e of graph.edges) {
    const sIn = S.has(e.source);
    const tIn = S.has(e.target);
    if (sIn && tIn) internalEdges.push(e);
    else if (!sIn && tIn) inEdges.push(e);
    else if (sIn && !tIn) outEdges.push(e);
    else externalEdges.push(e);
  }

  // 条件分支跨出边界:子图只有单一 output,无法再暴露 true/false 分支 → 拒绝。
  if (outEdges.some((e) => typeById.get(e.source) === "condition")) {
    return { ok: false, reason: "condition-branch" };
  }
  // 2. 凸性检查
  if (contractionHasCycle(graph, S, sgId, registry)) return { ok: false, reason: "not-convex" };

  // 3. 子图体节点:改写内部对外层源的引用 → input.*
  const inSources = new Set<string>();
  const bodyNodes: WNode[] = selNodes.map((n) => ({
    ...n,
    config: rewriteOuterRefs(n, registry, (src) => {
      if (S.has(src)) return null; // 内部引用,保持
      if (outerIds.has(src)) {
        inSources.add(src);
        return `input.${src}`; // 入边界:外层节点
      }
      return null; // loop/input/typo 等非节点 token,保持
    }),
  }));
  const bodyById = new Map(bodyNodes.map((n) => [n.id, n]));
  // 入边界数据边 → 目标节点 config 上的 {{input.u.so}} 模板
  for (const e of inEdges) {
    inSources.add(e.source);
    if (e.kind === "data" && e.source_output && e.target_input) {
      const tgt = bodyById.get(e.target);
      if (tgt) tgt.config = { ...(tgt.config ?? {}), [e.target_input]: `{{input.${e.source}.${e.source_output}}}` };
    }
  }

  // 4. inputs:每个入边界源喂整份输出
  const inputs: Record<string, string> = {};
  for (const u of [...inSources].sort()) inputs[u] = `{{${u}}}`;

  const sgNode: WNode = {
    id: sgId,
    type: "subgraph",
    name: opts.name,
    position: averagePosition(selNodes),
    config: { inputs, body: { nodes: bodyNodes, edges: internalEdges }, output: "" },
  };

  // 5. 外层保留节点:改写对内部节点的引用 → sg.output.*
  const keptNodes: WNode[] = graph.nodes
    .filter((n) => !S.has(n.id))
    .map((n) => ({
      ...n,
      config: rewriteOuterRefs(n, registry, (src) => (S.has(src) ? `${sgId}.output.${src}` : null)),
    }));
  const keptById = new Map(keptNodes.map((n) => [n.id, n]));
  // 出边界数据边 → 外层目标 config 上的 {{sg.output.v.so}} 模板
  for (const e of outEdges) {
    if (e.kind === "data" && e.source_output && e.target_input) {
      const tgt = keptById.get(e.target);
      if (tgt) tgt.config = { ...(tgt.config ?? {}), [e.target_input]: `{{${sgId}.output.${e.source}.${e.source_output}}}` };
    }
  }

  // 6. 外层边:外→外原样;入/出边界收缩成 u→sg / sg→w(去重;入边保留 source_handle)
  const newEdges: WEdge[] = [...externalEdges];
  const seen = new Set<string>();
  for (const e of inEdges) {
    const handle = e.source_handle ?? null;
    const key = `${e.source}->${sgId}#${handle ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    newEdges.push({ id: freshEdgeId(newEdges, e.source, sgId), source: e.source, target: sgId, source_handle: handle });
  }
  for (const e of outEdges) {
    const key = `${sgId}->${e.target}`;
    if (seen.has(key)) continue;
    seen.add(key);
    newEdges.push({ id: freshEdgeId(newEdges, sgId, e.target), source: sgId, target: e.target });
  }

  return { ok: true, graph: { nodes: [...keptNodes, sgNode], edges: newEdges }, subgraphId: sgId };
}

function freshEdgeId(edges: WEdge[], source: string, target: string): string {
  const base = `e-${source}-${target}`;
  const used = new Set(edges.map((e) => e.id));
  if (!used.has(base)) return base;
  let i = 1;
  while (used.has(`${base}-${i}`)) i += 1;
  return `${base}-${i}`;
}
