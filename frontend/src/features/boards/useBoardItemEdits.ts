/**
 * 就地改画布上某一格的几条路:写字、改名、通用的 patch;按媒体宽高比该把高度校正成多少(`aspectHeight`)。
 * 从 BoardCanvas 拆出来的钩子 —— 都只走 setNodes,不回写上层(见各自的说明)。
 */
import React from "react";
import type { Node } from "@xyflow/react";

import type { BoardItem } from "@/api/client";
import { DEFAULT_SIZE } from "@/features/boards/boardNodes";

/**
 * 媒体加载出来之后,节点高度该校正成它的**自然宽高比**下的多少;不用校正回 null。
 *
 * 不校正的话:一段 16:9 的视频摆在 320×200(1.6:1)的框里,上下各留一条黑边 —— 而画板上
 * 一眼扫过去看的就是画面本身,黑边等于把每个节点都缩小了一圈。图片同理。
 *
 * **只在还没被用户拉过时才校正**:他手动调过尺寸就是他的决定,不该被媒体加载覆盖回去。
 * 判据是宽高恰好等于默认值 —— 拉过的话至少有一边不是。
 *
 * 校正**不是人的一步**:画布把它并进撤销历史的当前这一份(见 BoardCanvas 的 fitAspect、useBoardHistory.absorb)。
 */
export function aspectHeight(node: Node, ratio: number): number | null {
  if (!Number.isFinite(ratio) || ratio <= 0) return null;
  const item = (node.data as unknown as { item?: BoardItem }).item;
  if (!item) return null;
  const preset = DEFAULT_SIZE[item.kind];
  const width = node.width ?? preset.width;
  const height = node.height ?? preset.height;
  if (width !== preset.width || height !== preset.height) return null;
  const next = Math.round(width / ratio);
  return next === height ? null : next;
}

export function useBoardItemEdits(setNodes: React.Dispatch<React.SetStateAction<Node[]>>) {
  // 文字改动直接落进节点 data —— 走 setNodes 而不是回写上层,理由同 BoardCanvas 开头那段:
  // 上层一变就重建节点,正在打字的 textarea 会失焦。
  const setText = React.useCallback((id: string, text: string): void => {
    setNodes((current: Node[]) =>
      current.map((node: Node) =>
        node.id === id
          ? { ...node, data: { ...node.data, item: { ...(node.data as { item: BoardItem }).item, text } } }
          : node,
      ),
    );
  }, []);

  /** 落下一个名字。空串 = 不要名字了:删掉字段,节点上方退回显示种类名。 */
  const setTitle = React.useCallback((id: string, title: string): void => {
    setNodes((current: Node[]) =>
      current.map((node: Node) => {
        if (node.id !== id) return node;
        const { title: _previous, ...rest } = (node.data as { item: BoardItem }).item;
        return { ...node, data: { ...node.data, item: title ? { ...rest, title } : rest } };
      }),
    );
  }, []);

  /** 把某一项就地换成已完成的产出。轮询拿到结果后由上层调。 */
  /**
   * 就地改某一项。**画布上的一切改动都走它** —— 填产出、写文字、标记开始生成,此前是三段
   * 各写一遍的 setNodes,而它们只在「改哪个字段」上不同。
   *
   * 值给 undefined 表示**删掉这个字段**；调用方不需要为不同字段各维护一套节点更新逻辑。
   */
  const patch = React.useCallback(
    (itemId: string, next: Partial<BoardItem>) => {
      setNodes((current) =>
        current.map((node) => {
          if (node.id !== itemId) return node;
          const item = { ...(node.data as unknown as { item: BoardItem }).item, ...next };
          for (const [key, value] of Object.entries(next)) {
            if (value === undefined) delete (item as Record<string, unknown>)[key];
          }
          return { ...node, data: { ...node.data, item } };
        }),
      );
    },
    [setNodes],
  );

  return { setText, setTitle, patch };
}
