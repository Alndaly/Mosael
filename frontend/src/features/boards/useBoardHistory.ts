/**
 * 画板画布的撤销 / 重做,以及「画布变了就汇一份给上层」。从 BoardCanvas 拆出来的钩子。
 */
import React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import type { Edge, Node } from "@xyflow/react";

import type { BoardCanvas as Canvas } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { redoSequence, undoSequence } from "@/api/domains/editor";
import { boardSequenceKey } from "@/features/boards/SequenceCell";
import { dropSequenceStep, emptyHistory, record, recordSequence, redo, retagSequenceStep, undo, type SequenceStep } from "@/features/boards/canvasHistory";
import { onSequenceEdit } from "@/features/boards/sequenceCursor";
import { LAYERS, toCanvas, toNodes } from "@/features/boards/boardCanvasModel";
import { toMarkerNodes } from "@/features/markers/markers";

export function useBoardHistory({
  nodes,
  edges,
  setNodes,
  setEdges,
  onChange,
}: {
  nodes: Node[];
  edges: Edge[];
  setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
  setEdges: React.Dispatch<React.SetStateAction<Edge[]>>;
  onChange: (canvas: Canvas) => void;
}) {
  const queryClient = useQueryClient();
  // 每次画布变了就汇一份给上层去存。**用 JSON 比对而不是引用比对** —— React Flow 每次
  // 拖动都换新对象,引用比对等于每帧都报"变了"。
  const serialized = React.useMemo(() => JSON.stringify(toCanvas(nodes, edges)), [nodes, edges]);
  React.useEffect(() => {
    onChange(JSON.parse(serialized) as Canvas);
  }, [serialized, onChange]);

  /**
   * 撤销/重做。存的是**整份画布的快照** —— 画板的事实来源是 React Flow 的 nodes/edges,
   * 撤销就是把某一份装回去(工作流那边挂在 zundo 上,因为它的事实来源是 store 里的 graph)。
   */
  const [history, setHistory] = React.useState(() => emptyHistory(serialized));
  //: 正在装回去的那一份 —— 它引发的这一轮变化**不能再进历史**,否则撤一步会立刻被记成
  //: 一次新编辑,重做就永远回不去了(表现是「撤销键按一下就灰了」)。
  const restoring = React.useRef<string | null>(null);

  /** 把一份画布装进 React Flow,回它装进去之后序列化出来的样子(和 `serialized` 同一种写法)。 */
  const load = React.useCallback(
    (canvas: Canvas): string => {
      const nextNodes = [...toNodes(canvas.items), ...toMarkerNodes(canvas.markers ?? [], LAYERS.marker)];
      const nextEdges = canvas.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target }));
      setNodes(nextNodes);
      setEdges(nextEdges);
      return JSON.stringify(toCanvas(nextNodes, nextEdges));
    },
    [setNodes, setEdges],
  );

  const restore = React.useCallback(
    (snapshot: string) => {
      restoring.current = load(JSON.parse(snapshot) as Canvas);
    },
    [load],
  );

  /**
   * 换成服务端那份(冲突之后、或回执落地时采用服务端画布)。**历史从这一份重新开始。**
   *
   * 之前那摞快照都建立在一份已经不成立的画布上:撤一步装回去的是「别人改之前」的样子 ——
   * 智能体刚加的便签、别处刚落回的产出一起消失,下一次自动保存再带着新版本号把它们存没了。
   */
  const replace = React.useCallback(
    (canvas: Canvas) => {
      const snapshot = load(canvas);
      restoring.current = snapshot;
      setHistory(emptyHistory(snapshot));
    },
    [load],
  );

  React.useEffect(() => {
    if (restoring.current === serialized) {
      restoring.current = null;
      return;
    }
    //: **攒一下再记。** 拖一个节点会发几十次位置更新,一次一步的话用户得按几十下撤销
    //: 才回得到上一个状态。
    const timer = setTimeout(() => setHistory((current) => record(current, serialized)), 400);
    return () => clearTimeout(timer);
  }, [serialized]);

  //: 时间线格里做成的一步记进这摞(见 canvasHistory 的「时间线的一步」)。
  React.useEffect(
    () => onSequenceEdit((sequenceId, revision) => setHistory((current) => recordSequence(current, sequenceId, revision))),
    [],
  );

  /** 撤 / 重做时间线格的一步:带着这一步记的版本号调那条时间线自己的撤销 / 重做(时间线在别处又改过就被拒,
   *  不撤别人的那一步),格子读的缓存换成回来的那条。做成了,这一步的版本号换成新的一版;没做成,这一步拿掉。 */
  const replaySequence = React.useCallback((step: SequenceStep, direction: "undo" | "redo") => {
    //: 撤销之后这一步挪进了重做的开头,重做之后回到了撤销的末尾。
    const where = direction === "undo" ? "future" : "past";
    void (direction === "undo" ? undoSequence(step.sequence, step.revision) : redoSequence(step.sequence, step.revision))
      .then((next) => {
        queryClient.setQueryData(boardSequenceKey(step.sequence), next);
        setHistory((current) => retagSequenceStep(current, where, next.revision));
      })
      .catch((error: unknown) => {
        setHistory((current) => dropSequenceStep(current, where));
        toast.error(errorText(error));
      });
  }, [queryClient]);

  //: 撤销 / 重做在更新函数**外面**算下一份、做副作用:时间线的撤销是一次网络请求,放进 setState 的更新函数里,
  //: 开发模式下更新函数跑两遍就撤了两步。
  const historyRef = React.useRef(history);
  historyRef.current = history;
  const stepBack = React.useCallback(() => {
    const current = historyRef.current;
    const next = undo(current);
    if (!next) return;
    historyRef.current = next;
    setHistory(next);
    const step = current.past.at(-1);
    if (typeof step === "object") replaySequence(step, "undo");
    else restore(next.present);
  }, [restore, replaySequence]);

  const stepForward = React.useCallback(() => {
    const current = historyRef.current;
    const next = redo(current);
    if (!next) return;
    historyRef.current = next;
    setHistory(next);
    const step = current.future[0];
    if (typeof step === "object") replaySequence(step, "redo");
    else restore(next.present);
  }, [restore, replaySequence]);

  return { history, replace, stepBack, stepForward };
}
