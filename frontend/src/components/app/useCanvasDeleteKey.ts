import React from "react";

import { isCanvasKeyTarget, listenKeys } from "@/lib/shortcuts";

interface Selectable {
  id: string;
  selected?: boolean;
  deletable?: boolean;
}

/** 用到的那一小截 React Flow 实例:谁选中了、删掉它们。 */
interface DeletableCanvas<N extends Selectable, E extends Selectable> {
  getNodes(): N[];
  getEdges(): E[];
  deleteElements(params: { nodes: N[]; edges: E[] }): unknown;
}

/**
 * Backspace / Delete 删掉画布上选中的节点和连线 —— **只在按键冲着画布时**(见 isCanvasKeyTarget)。
 *
 * 画布挂上它的同时要把 React Flow 自带的删除键关掉(`deleteKeyCode={null}`):那一套听的是整个
 * document,只放过输入框和 `.nokey`。于是焦点停在浮在节点上的面板按钮上、或者在 Portal 到 body
 * 的下拉选项上时按 Backspace,删掉的是**正在编辑的那一格**。工作流编辑器先修了一遍,画板还是
 * 老样子 —— 所以这一条收成一处,每块 React Flow 画布都用它。
 *
 * 删除照旧走 React Flow 的 deleteElements,于是经 onNodesChange / onEdgesChange 落进各自的图里
 * (撤销、脏标记、连带清理都是原来那一套),这里只判「这一下算不算」。
 */
export function useCanvasDeleteKey<N extends Selectable, E extends Selectable>(
  editor: React.RefObject<Element | null>,
  canvas: React.RefObject<DeletableCanvas<N, E> | null>,
): void {
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Backspace" && event.key !== "Delete") return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!isCanvasKeyTarget(event.target, editor.current)) return;
      const instance = canvas.current;
      if (!instance) return;
      const doomedNodes = instance.getNodes().filter((node) => node.selected && node.deletable !== false);
      const doomedEdges = instance.getEdges().filter((edge) => edge.selected && edge.deletable !== false);
      if (doomedNodes.length === 0 && doomedEdges.length === 0) return;
      event.preventDefault();
      void instance.deleteElements({ nodes: doomedNodes, edges: doomedEdges });
    };
    return listenKeys(window, onKey);
    // 两个 ref 本身不变,读的都是 .current。
  }, [editor, canvas]);
}
