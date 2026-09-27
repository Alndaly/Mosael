/**
 * 工作流文件(`.mosael-workflow.json`)在官网这一侧的两件事:
 *
 * 1. **提交前预览**:作者选了文件,先在浏览器里认一下它是不是应用导出的那种文件、有几个节点、
 *    有没有「运行代码」节点,画出节点图 —— 真正的校验在社区服务(和桌面应用同一套)。
 * 2. **画节点图**:详情页和提交页共用。节点带着应用里的坐标(`position`)就照坐标画 —— 作者
 *    在应用里怎么摆的,这里就是什么样;缺坐标时按依赖分层,自己排。
 */
import type { WorkflowEdge, WorkflowGraph, WorkflowNode } from "@/lib/community/types";

/** 会在别人机器上执行代码的节点类型(应用里的「运行代码」)。 */
export const CODE_NODE_TYPES: ReadonlySet<string> = new Set(["code"]);

export type WorkflowEnvelope = {
  name: string;
  description: string;
  graph: WorkflowGraph;
};

export type EnvelopeProblem = "not_json" | "not_workflow" | "no_nodes";

/** 认一下文件的外形。**不是校验**:只挡住明显选错的文件。 */
export function readWorkflowEnvelope(text: string): { ok: true; envelope: WorkflowEnvelope } | { ok: false; problem: EnvelopeProblem } {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return { ok: false, problem: "not_json" };
  }
  if (!raw || typeof raw !== "object") return { ok: false, problem: "not_workflow" };
  const record = raw as { format?: unknown; name?: unknown; description?: unknown; graph?: unknown };
  if (record.format !== "mosael-workflow" || !record.graph || typeof record.graph !== "object") return { ok: false, problem: "not_workflow" };
  const graph = record.graph as { nodes?: unknown; edges?: unknown; meta?: unknown };
  const nodes = Array.isArray(graph.nodes) ? graph.nodes.filter(isNode) : [];
  if (nodes.length === 0) return { ok: false, problem: "no_nodes" };
  const edges = Array.isArray(graph.edges) ? graph.edges.filter(isEdge) : [];
  return {
    ok: true,
    envelope: {
      name: typeof record.name === "string" ? record.name : "",
      description: typeof record.description === "string" ? record.description : "",
      graph: { nodes, edges, meta: (graph.meta ?? undefined) as WorkflowGraph["meta"] },
    },
  };
}

function isNode(value: unknown): value is WorkflowNode {
  return Boolean(value) && typeof (value as WorkflowNode).id === "string" && typeof (value as WorkflowNode).type === "string";
}

function isEdge(value: unknown): value is WorkflowEdge {
  return Boolean(value) && typeof (value as WorkflowEdge).source === "string" && typeof (value as WorkflowEdge).target === "string";
}

export function hasCodeNodes(graph: WorkflowGraph): boolean {
  return graph.nodes.some((node) => CODE_NODE_TYPES.has(node.type));
}

export const NODE_WIDTH = 188;
export const NODE_HEIGHT = 52;
const GAP_X = 72;
const GAP_Y = 28;

export type PlacedNode = WorkflowNode & { x: number; y: number; code: boolean };
export type PlacedEdge = { id: string; path: string; from: PlacedNode; to: PlacedNode };
export type GraphLayout = { nodes: PlacedNode[]; edges: PlacedEdge[]; width: number; height: number };

/**
 * 缺坐标时的分层:每个节点的层 = 从起点到它的最长路径。环(不该有,但文件是外面来的)先按节点
 * 顺序做一遍深度优先,把指回栈上节点的那几条边(回边)拿掉,剩下的一定是 DAG。
 */
function layered(nodes: WorkflowNode[], edges: WorkflowEdge[]): Map<string, { x: number; y: number }> {
  const ids = new Set(nodes.map((node) => node.id));
  const outgoing = new Map<string, string[]>();
  for (const edge of edges) {
    if (!ids.has(edge.source) || !ids.has(edge.target)) continue;
    outgoing.set(edge.source, [...(outgoing.get(edge.source) ?? []), edge.target]);
  }
  const state = new Map<string, "open" | "done">();
  const incoming = new Map<string, string[]>();
  const visit = (id: string) => {
    state.set(id, "open");
    for (const next of outgoing.get(id) ?? []) {
      if (state.get(next) === "open") continue; // 回边:丢掉
      incoming.set(next, [...(incoming.get(next) ?? []), id]);
      if (!state.has(next)) visit(next);
    }
    state.set(id, "done");
  };
  for (const node of nodes) if (!state.has(node.id)) visit(node.id);

  const depth = new Map<string, number>();
  const depthOf = (id: string): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    const value = Math.max(-1, ...(incoming.get(id) ?? []).map(depthOf)) + 1;
    depth.set(id, value);
    return value;
  };
  const rows = new Map<number, number>();
  const placed = new Map<string, { x: number; y: number }>();
  for (const node of nodes) {
    const column = depthOf(node.id);
    const row = rows.get(column) ?? 0;
    rows.set(column, row + 1);
    placed.set(node.id, { x: column * (NODE_WIDTH + GAP_X), y: row * (NODE_HEIGHT + GAP_Y) });
  }
  return placed;
}

/** 摆好每个节点、连好每条线,整张图平移到从 (0,0) 开始。 */
export function layoutGraph(graph: WorkflowGraph): GraphLayout {
  const nodes = graph.nodes;
  const positioned = nodes.every((node) => node.position && Number.isFinite(node.position.x) && Number.isFinite(node.position.y));
  const auto = positioned ? null : layered(nodes, graph.edges);
  const raw = nodes.map((node) => {
    const at = auto ? auto.get(node.id)! : node.position!;
    return { ...node, x: at.x, y: at.y, code: CODE_NODE_TYPES.has(node.type) };
  });
  const minX = Math.min(...raw.map((node) => node.x));
  const minY = Math.min(...raw.map((node) => node.y));
  const placed = raw.map((node) => ({ ...node, x: node.x - minX, y: node.y - minY }));
  const byId = new Map(placed.map((node) => [node.id, node]));
  const edges: PlacedEdge[] = [];
  graph.edges.forEach((edge, index) => {
    const from = byId.get(edge.source);
    const to = byId.get(edge.target);
    if (!from || !to) return;
    const x1 = from.x + NODE_WIDTH;
    const y1 = from.y + NODE_HEIGHT / 2;
    const x2 = to.x;
    const y2 = to.y + NODE_HEIGHT / 2;
    const bend = Math.max(40, Math.abs(x2 - x1) / 2);
    edges.push({ id: edge.id ?? `e${index}`, path: `M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}`, from, to });
  });
  return {
    nodes: placed,
    edges,
    width: Math.max(...placed.map((node) => node.x + NODE_WIDTH)),
    height: Math.max(...placed.map((node) => node.y + NODE_HEIGHT)),
  };
}
