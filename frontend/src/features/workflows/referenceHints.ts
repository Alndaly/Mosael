import React from "react";
import type { Edge } from "@xyflow/react";

import type { WorkflowGraph } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import type { EdgeShape } from "@/components/app/canvasEdgeShape";
import { canvasEdgeClass } from "@/components/app/canvasEdges";
import { layerReferences, neverRunReferences, type RegistryLike } from "@/features/workflows/analyze";

/**
 * 画布上的**引用提示线**:每一处 `{{A.x}}`,从 A 的 x 口(找不到具体口就从节点)到引用它的节点画一根淡点线。
 *
 * 引用即依赖(后端 graph_rules.reference_dependencies):引擎等 A 落定才跑引用它的节点 —— 可这件事此前只写在
 * 提示词里,画布上看不见。「从主题到完整视频」里「按画幅取尺寸 → 建项目」那几处先后只靠引用;「可用的 3D 道具」
 * 只靠一句引用挂着、没接进流程,从模板 v8 到 v11 一次都没跑过。画出来,谁等谁、谁根本不会跑,看图就知道。
 *
 * 它**不是连线**:不在图里(只在显示时叠上去),不能选中、删除、拖去重连,也不参与连线校验(连线校验读的是图);
 * 两头之间已经有真连线(同一个方向)的不再画。被引用的节点一定不会跑、而引用方会跑时用错误色 —— 和就绪检查的
 * unwired-referenced、后端运行前拦的那一条是同一对(analyze.neverRunReferences)。长什么样见 components/app/canvasEdges。
 */

/** React Flow 里这种线的类型名(渲染器见 ReferenceHintEdge)。 */
export const REFERENCE_HINT_EDGE_TYPE = "reference-hint";

/** 提示线的 id 都带这个前缀:和图里的连线 id 分得开,画布上的改动回调认得出它不是图的一部分。 */
export const REFERENCE_HINT_ID_PREFIX = "ref-hint:";

export function isReferenceHintId(id: string): boolean {
  return id.startsWith(REFERENCE_HINT_ID_PREFIX);
}

type NodeMeta = NonNullable<ReturnType<RegistryLike["get"]>>;

/** 画提示线要读的:引用的口径(代码字段、体字段,同 analyze.layerReferences)和节点声明的输出。 */
export interface HintRegistry extends RegistryLike {
  get(type: string): (NodeMeta & { outputs?: readonly string[]; label?: string }) | undefined;
}

export interface ReferenceHint {
  id: string;
  source: string;
  /** A 的输出口(`out:x`);找不到具体口(开始节点的参数、条件节点、没声明的输出)就是 null —— 从节点的出口出发。 */
  sourceHandle: string | null;
  target: string;
  /** 这一根线代表的引用写法(同一个口被引用几处只画一根)。 */
  refs: string[];
  /** 被引用的节点一定不会跑,而引用方会跑:运行前会被拦。 */
  neverRuns: boolean;
}

/**
 * A 的 `output` 在卡片上有没有自己的口:声明里有它、不是通配(开始节点的 `*params`),而且这个节点画输出口 ——
 * 条件节点只画真 / 假两路出口(见 WorkflowNode 的 isCondition)。
 */
function outputHandle(registry: HintRegistry, nodeType: string, output: string): string | null {
  if (!output || output.startsWith("*") || nodeType === "condition") return null;
  return (registry.get(nodeType)?.outputs ?? []).includes(output) ? `out:${output}` : null;
}

const pair = (source: string, target: string) => JSON.stringify([source, target]);

/** 这一层图里该画的引用提示线。`entryIsRoot`:这一层是循环体 / 子图(无入边的根也是入口,见 analyze.neverRunNodes)。 */
export function referenceHints(
  graph: WorkflowGraph,
  registry: HintRegistry,
  { entryIsRoot }: { entryIsRoot: boolean },
): ReferenceHint[] {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  const wired = new Set(graph.edges.map((edge) => pair(edge.source, edge.target)));
  const neverRuns = new Set(
    neverRunReferences(graph, registry, { entryIsRoot }).flatMap((one) =>
      one.referencedBy.map((target) => pair(one.source, target)),
    ),
  );
  const hints = new Map<string, ReferenceHint>();
  for (const node of graph.nodes) {
    //: 开始节点没有入口可接(它自己就是入口)。
    if (node.type === "start") continue;
    for (const { ref, sourceId } of layerReferences(node, registry)) {
      const source = nodes.get(sourceId);
      if (!source || sourceId === node.id || wired.has(pair(sourceId, node.id))) continue;
      const handle = outputHandle(registry, source.type, ref.slice(2, -2).split(".")[1] ?? "");
      const id = `${REFERENCE_HINT_ID_PREFIX}${sourceId}>${handle ?? ""}>${node.id}`;
      const hint = hints.get(id) ?? {
        id,
        source: sourceId,
        sourceHandle: handle,
        target: node.id,
        refs: [],
        neverRuns: neverRuns.has(pair(sourceId, node.id)),
      };
      if (!hint.refs.includes(ref)) hint.refs.push(ref);
      hints.set(id, hint);
    }
  }
  return [...hints.values()];
}

export interface ReferenceHintEdgeData extends Record<string, unknown> {
  kind: "reference-hint";
  /** 悬停时那句说明(也是这根线的无障碍名字)。 */
  title: string;
  shape: EdgeShape;
  neverRuns: boolean;
}

export type ReferenceHintFlowEdge = Edge<ReferenceHintEdgeData, typeof REFERENCE_HINT_EDGE_TYPE>;

/** 提示线 → React Flow 的边:淡点线、无箭头,不能选、删、拖去重连,也不进 Tab 序。 */
export function toReferenceHintEdges(
  hints: readonly ReferenceHint[],
  { shape, t, nodeName }: { shape: EdgeShape; t: (key: MessageKey) => string; nodeName: (id: string) => string },
): ReferenceHintFlowEdge[] {
  return hints.map((hint) => {
    const title = t(hint.neverRuns ? "wfRefHintNeverRuns" : "wfRefHint")
      .replace("{refs}", hint.refs.join(t("listSeparator")))
      .replace("{source}", nodeName(hint.source));
    return {
      id: hint.id,
      source: hint.source,
      target: hint.target,
      sourceHandle: hint.sourceHandle ?? undefined,
      type: REFERENCE_HINT_EDGE_TYPE,
      className: canvasEdgeClass(hint.neverRuns ? "ref-never-runs" : "ref", { hint: true }),
      //: 写成 undefined 是为了**盖掉** defaultEdgeOptions 的默认箭头:提示线不画箭头。
      markerEnd: undefined,
      selectable: false,
      deletable: false,
      focusable: false,
      reconnectable: false,
      //: 命中带收窄:它只为了悬停看说明,不该从旁边的真连线、空白处抢走指针。
      interactionWidth: 10,
      ariaLabel: title,
      data: { kind: REFERENCE_HINT_EDGE_TYPE, title, shape, neverRuns: hint.neverRuns },
    };
  });
}

/**
 * 两张图的**结构**一样吗:节点的 id、类型、名字、配置(按引用比),和连线(按引用比)。拖动只换节点的位置 ——
 * 位置变了而结构没变时,提示线不必重算(拖动一下会连发几十次)。
 */
export function sameStructure(a: WorkflowGraph, b: WorkflowGraph): boolean {
  if (a === b) return true;
  if (a.edges !== b.edges || a.nodes.length !== b.nodes.length) return false;
  return a.nodes.every((node, index) => {
    const other = b.nodes[index];
    return node === other || (node.id === other.id && node.type === other.type && node.name === other.name && node.config === other.config);
  });
}

/** 画布这一层的引用提示线。只在图的结构变了时重算(见 sameStructure);走线方式、语言换了才重新生成边。 */
export function useReferenceHintEdges(
  graph: WorkflowGraph,
  registry: HintRegistry,
  { entryIsRoot, shape, t }: { entryIsRoot: boolean; shape: EdgeShape; t: (key: MessageKey) => string },
): ReferenceHintFlowEdge[] {
  //: 「结构没变就沿用上一份」—— 在渲染中对齐(React 文档里「随 props 调整 state」的写法),不用 effect 慢一帧。
  const [structure, setStructure] = React.useState(graph);
  if (structure !== graph && !sameStructure(structure, graph)) setStructure(graph);
  const hints = React.useMemo(() => referenceHints(structure, registry, { entryIsRoot }), [structure, registry, entryIsRoot]);
  return React.useMemo(() => {
    const names = new Map(structure.nodes.map((node) => [node.id, node.name || registry.get(node.type)?.label || node.type]));
    return toReferenceHintEdges(hints, { shape, t, nodeName: (id) => names.get(id) ?? id });
  }, [hints, structure, registry, shape, t]);
}
