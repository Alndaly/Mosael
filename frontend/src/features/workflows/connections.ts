/** 画布连线合法性里的纯逻辑(UI 无关、可单测)。核心是「查重要按边的种类分开」:
 *  本 app 有两类边——控制边(顺序,节点→节点,可带条件 handle)与数据边(属性,输出接点
 *  out:x → 输入接点 in:y,用 source_output/target_input)。数据边**不存 source_handle**,
 *  值为空;若查重时不分种类,它就会和「无 handle 的控制边」撞车,导致「先连属性再连顺序」
 *  时把已有数据边误判成重复、把控制边拒掉。 */
import type { WorkflowGraph } from "../../api/client";

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
