/** 画布连线合法性里的纯逻辑(UI 无关、可单测)。核心是「查重要按边的种类分开」:
 *  本 app 有两类边——控制边(顺序,节点→节点,可带条件 handle)与数据边(属性,输出接点
 *  out:x → 输入接点 in:y,用 source_output/target_input)。数据边**不存 source_handle**,
 *  值为空;若查重时不分种类,它就会和「无 handle 的控制边」撞车,导致「先连属性再连顺序」
 *  时把已有数据边误判成重复、把控制边拒掉。 */
import type { WorkflowGraph } from "../../api/client";
import { dependentsCleared, type DependencySpec } from "../nodeForms/dependents";

type WEdge = WorkflowGraph["edges"][number];

/** 拖动中的连接是不是数据边(从输出接点 out:x 拖到输入接点 in:y)。 */
export function isDataConnection(
  srcHandle: string | null | undefined,
  tgtHandle: string | null | undefined,
): boolean {
  return !!srcHandle?.startsWith("out:") && !!tgtHandle?.startsWith("in:");
}

/** 一条**控制边**是否与已有边重复:只跟同类控制边比 (source, target, source_handle)。
 *  数据边不参与(它的去重由 onConnect 按 target_input 替换处理)。 */
export function isDuplicateControlEdge(
  edges: WEdge[],
  source: string,
  target: string,
  srcHandle: string | undefined,
): boolean {
  return edges.some(
    (edge) =>
      edge.kind !== "data" &&
      edge.source === source &&
      edge.target === target &&
      (edge.source_handle ?? undefined) === (srcHandle ?? undefined),
  );
}

/**
 * 把 `targetId` 节点的输入 `key` 接到 `sourceId` 的 `output`:建 / 换那条数据边、`key` 进连接态、
 * 字面量清空交给数据边供值。
 *
 * **依赖 `key` 的字段一并清掉**(声明里的 `depends_on`):换接了另一条时间线,手里那条轨道 id 就不在
 * 新时间线上了 —— 两格各自都有值、界面看着正常,跑起来才报「这条时间线上没有那条轨道」。
 * 画布上拖线和检查器里挑来源是同一件事,两处都走这里。
 *
 * **来源和输出都没变就原样返回**(下拉里重选同一项、画布上把同一条线重拖一遍):值从哪来没换,
 * 接好之后才填的轨道不该被清掉。
 */
export function withDataInputBound(
  graph: WorkflowGraph,
  binding: { targetId: string; key: string; sourceId: string; output: string },
  specs: Record<string, DependencySpec | undefined>,
): WorkflowGraph {
  const { targetId, key, sourceId, output } = binding;
  const same = graph.edges.some(
    (edge) =>
      edge.kind === "data" &&
      edge.target === targetId &&
      edge.target_input === key &&
      edge.source === sourceId &&
      edge.source_output === output,
  );
  if (same) return graph;
  const id = `d-${sourceId}-${output}-${targetId}-${key}`;
  return {
    ...graph,
    edges: [
      ...graph.edges.filter((edge) => !(edge.kind === "data" && edge.target === targetId && edge.target_input === key)),
      { id, source: sourceId, target: targetId, kind: "data", source_output: output, target_input: key },
    ],
    nodes: graph.nodes.map((node) =>
      node.id === targetId
        ? {
            ...node,
            inputs: [...new Set([...(node.inputs ?? []), key])],
            config: dependentsCleared({ ...(node.config ?? {}), [key]: "" }, key, specs),
          }
        : node,
    ),
  };
}
