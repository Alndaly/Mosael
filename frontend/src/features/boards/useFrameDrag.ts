/**
 * 拖动分组框时带着框里的几项一起走。从 BoardCanvas 拆出来的钩子;判定规则在 frameCarry.ts。
 */
import React from "react";
import type { Node } from "@xyflow/react";

import type { BoardItem } from "@/api/client";
import { carriedByFrame } from "@/features/boards/frameCarry";
import { DEFAULT_SIZE } from "@/features/boards/boardNodes";

export function useFrameDrag({ nodes, setNodes }: { nodes: Node[]; setNodes: React.Dispatch<React.SetStateAction<Node[]>> }) {
  /**
   * 拖动分组框时被它带着走的那几项。
   *
   * **在按下的那一刻定下来,拖的过程中不再变。** 边拖边判「谁在框里」的话,框扫过谁就会
   * 顺手把谁卷走 —— 用户只是想把这一组挪到右边,结果沿途的东西全被推到了一起。
   */
  const carried = React.useRef<{ id: string; from: { x: number; y: number } }[]>([]);
  const dragFrom = React.useRef<{ x: number; y: number } | null>(null);

  const beginFrameDrag = React.useCallback(
    (node: Node) => {
      const item = (node.data as unknown as { item?: BoardItem }).item;
      carried.current = [];
      dragFrom.current = null;
      // 标记节点没有 item(它不是画板项)—— 不先问一句,拖一枚旗子就会在这里抛。
      if (!item || item.kind !== "frame" || !item.move_children) return;
      const left = node.position.x;
      const top = node.position.y;
      const right = left + (node.width ?? DEFAULT_SIZE.frame.width);
      const bottom = top + (node.height ?? DEFAULT_SIZE.frame.height);
      dragFrom.current = { ...node.position };
      //: 判定规则在 frameCarry.ts —— 它是一条规则不是渲染,而它出过一个只有嵌套时
      //: 才看得见的错(外框把内框里的东西带走了,却把内框留在原地)。
      const positions = new Map(nodes.map((one) => [one.id, one.position]));
      carried.current = carriedByFrame(
        { id: node.id, kind: "frame", x: left, y: top, width: right - left, height: bottom - top },
        nodes.map((one) => ({
          id: one.id,
          kind: String(one.type ?? ""),
          x: one.position.x,
          y: one.position.y,
          width: one.width ?? 0,
          height: one.height ?? 0,
        })),
      ).map((one) => ({ id: one.id, from: { ...(positions.get(one.id) ?? { x: one.x, y: one.y }) } }));
    },
    [nodes],
  );

  const dragFrame = React.useCallback(
    (node: Node) => {
      const from = dragFrom.current;
      if (!from || carried.current.length === 0) return;
      //: 位移始终从**按下时**的位置算起,不是上一帧 —— 逐帧累加的话,某一帧被丢掉
      //: (拖得快时会)就永久错开一段。
      const dx = node.position.x - from.x;
      const dy = node.position.y - from.y;
      const moves = new Map(carried.current.map((one) => [one.id, one.from]));
      setNodes((current) =>
        current.map((one) => {
          const origin = moves.get(one.id);
          return origin ? { ...one, position: { x: origin.x + dx, y: origin.y + dy } } : one;
        }),
      );
    },
    [setNodes],
  );

  const endFrameDrag = React.useCallback(() => {
    carried.current = [];
    dragFrom.current = null;
  }, []);

  return { beginFrameDrag, dragFrame, endFrameDrag };
}
