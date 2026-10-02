/**
 * 画板画布的撤销 / 重做,以及「画布变了就汇一份给上层」。从 BoardCanvas 拆出来的钩子。
 */
import React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import type { Edge, Node } from "@xyflow/react";

import type { BoardCanvas as Canvas, BoardItem } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { redoSequence, undoSequence } from "@/api/domains/editor";
import { boardSequenceKey } from "@/features/boards/SequenceCell";
import { dropSequenceStep, emptyHistory, joinSequenceToCanvas, record, recordSequence, redo, retagSequenceStep, undo, type SequenceStep } from "@/features/boards/canvasHistory";
import { onSequenceEdit } from "@/features/boards/sequenceCursor";
import { LAYERS, toCanvas, toNodes } from "@/features/boards/boardCanvasModel";
import { withServerOwned } from "@/features/boards/boardServerOwned";
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
  //: 采用服务端那一版时要按 id 找回节点此刻的选中态(见 adopt);回调里读最新的,不进依赖。
  const nodesRef = React.useRef(nodes);
  nodesRef.current = nodes;
  const graph = React.useRef({ nodes, edges });
  graph.current = { nodes, edges };
  const onChangeRef = React.useRef(onChange);
  onChangeRef.current = onChange;

  /**
   * 撤销/重做。存的是**整份画布的快照** —— 画板的事实来源是 React Flow 的 nodes/edges,
   * 撤销就是把某一份装回去(工作流那边挂在 zundo 上,因为它的事实来源是 store 里的 graph)。
   */
  const [history, setHistory] = React.useState(() => emptyHistory(JSON.stringify(toCanvas(nodes, edges))));
  //: 上一次汇给上层的那一份(和历史里存的是同一种写法)。挂上时就是这一份 —— 加载进来不是编辑,不汇。
  const emitted = React.useRef(history.present);
  //: 正在装回去的那一份 —— 它引发的这一轮变化**不能再进历史**,否则撤一步会立刻被记成
  //: 一次新编辑,重做就永远回不去了(表现是「撤销键按一下就灰了」)。
  const restoring = React.useRef<string | null>(null);
  //: 服务端落下、人还没亲手删过的格子(一项能力的产出、一次多张的其余几张、智能体加的、产出落进来的那一格):
  //: 撤销 / 重做回到更早的一份时补回去(见 boardServerOwned)。人删了它就归人了 —— 撤销、重做照人的那几步来。
  const landed = React.useRef(new Set<string>());

  /**
   * 画布变了:**攒一下再序列化一次**,汇给上层(自动保存、查找)和记进撤销历史的是同一份。
   *
   * 此前每一帧都 JSON.stringify 整张画布、再 JSON.parse 一遍交给上层 —— 拖一格,大画板上每帧几毫秒到几十毫秒,
   * 上层还跟着每帧重渲染一次。现在攒到停手 400ms(和撤销的并步是同一个窗口:拖一下是一步)再做一次。
   * **按 JSON 比对**:React Flow 每次拖动都换新对象,选中一格也换 —— 内容没变就不汇、不记。
   * 要服务端照着画布去做的动作(生成、写字)等不了这 400ms,先 `flush()` 拿现在这一份(见 BoardsView.run)。
   */
  const settle = React.useCallback((): Canvas => {
    const canvas = toCanvas(graph.current.nodes, graph.current.edges);
    const snapshot = JSON.stringify(canvas);
    if (snapshot !== emitted.current) {
      emitted.current = snapshot;
      onChangeRef.current(canvas);
    }
    const restored = restoring.current === snapshot;
    restoring.current = null;
    if (!restored) {
      const alive = new Set(canvas.items.map((item) => item.id));
      for (const id of landed.current) if (!alive.has(id)) landed.current.delete(id);
      setHistory((current) => record(current, snapshot));
    }
    return canvas;
  }, []);
  const pending = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  React.useEffect(() => {
    if (pending.current) clearTimeout(pending.current);
    pending.current = setTimeout(() => {
      pending.current = null;
      settle();
    }, 400);
  }, [nodes, edges, settle]);
  React.useEffect(
    () => () => {
      //: 卸载时把攒着的那一次汇出去 —— 拖完最后一下就切走,自动保存还要把它补上。
      if (pending.current) {
        clearTimeout(pending.current);
        settle();
      }
    },
    [settle],
  );
  /** 不等攒够,现在就把画布汇出去,回这一份。 */
  const flush = React.useCallback((): Canvas => {
    if (pending.current) {
      clearTimeout(pending.current);
      pending.current = null;
    }
    return settle();
  }, [settle]);

  /** 把一份画布装进 React Flow,回它装进去之后序列化出来的样子(和 settle 同一种写法)。 */
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

  /** 撤 / 重做回到一份快照:服务端归属的东西照画布此刻的补回去(在跑的、落下的产出和格子),只在这一下做。 */
  const restore = React.useCallback(
    (snapshot: string) => {
      const current = toCanvas(graph.current.nodes, graph.current.edges);
      restoring.current = load(withServerOwned(JSON.parse(snapshot) as Canvas, current, landed.current));
    },
    [load],
  );

  /**
   * 采用服务端的新一版(回执落地、智能体改了板、保存撞了版本号之后合好的那份),**撤销历史不清空、也不改写**。
   *
   * `canvas` 是已经把本地改动重放上去的那份(boardRebase)。撤销栈里那几份快照原样留着:撤到更早的一份时,服务端
   * 落下的东西在**应用那一份时**补回去(restore → boardServerOwned)—— 撤一步回到的样子里照样有刚出的图,在跑的
   * 一格也撤不成空槽。此前每采用一次就把整摞快照按它合一遍:慢(100 份 × 1000 格约一秒),还合错(本地新放、后来
   * 开跑的一格在更早的快照里不存在,被当成删掉的)。
   *
   * 节点按 id 就地换:选中、量出来的尺寸留着 —— 回执每落一次选中的那一格就被取消选中,面板就收起来了。
   */
  const adopt = React.useCallback(
    (canvas: Canvas) => {
      const before = new Map(nodesRef.current.map((node) => [node.id, node]));
      const nextNodes = [...toNodes(canvas.items), ...toMarkerNodes(canvas.markers ?? [], LAYERS.marker)].map((node) => {
        const old = before.get(node.id);
        return old ? { ...node, selected: old.selected, measured: old.measured } : node;
      });
      //: 记下服务端这一版落下的:本地没有的新格子,和产出刚落进来的那一格。
      for (const item of canvas.items) {
        const was = (before.get(item.id)?.data as { item?: BoardItem } | undefined)?.item;
        const output = Boolean(item.asset_id) && item.run?.status === "succeeded" && was?.asset_id !== item.asset_id;
        if (!was || output) landed.current.add(item.id);
      }
      const nextEdges = canvas.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target }));
      setNodes(nextNodes);
      setEdges(nextEdges);
      const snapshot = JSON.stringify(toCanvas(nextNodes, nextEdges));
      restoring.current = snapshot;
      setHistory((current) => ({ ...current, present: snapshot }));
    },
    [setNodes, setEdges],
  );

  //: 时间线格里做成的一步记进这摞(见 canvasHistory 的「时间线的一步」)。连一根线进时间线格引起的那一步,和画布上
  //: 那根线并成一步:先把攒着的画布变化记下(线已经在画布上了),再把两步并起来。
  React.useEffect(
    () =>
      onSequenceEdit((sequenceId, revision, link) => {
        if (link) flush();
        setHistory(
          (current) =>
            (link && joinSequenceToCanvas(current, sequenceId, revision, link)) || recordSequence(current, sequenceId, revision),
        );
      }),
    [flush],
  );

  /** 撤 / 重做时间线格的一步:带着这一步记的版本号调那条时间线自己的撤销 / 重做(时间线在别处又改过就被拒,
   *  不撤别人的那一步),格子读的缓存换成回来的那条。做成了,这一步的版本号换成新的一版;没做成,这一步拿掉。 */
  const replaySequence = React.useCallback((step: SequenceStep, direction: "undo" | "redo") => {
    //: 撤销之后这一步挪进了重做的开头,重做之后回到了撤销的末尾。
    const where = direction === "undo" ? "future" : "past";
    //: 一步里连着几次操作(一次批量连进来接了几段):一次接一次地撤 / 重做,每次带上上一次回来的版本号。
    const replay = async () => {
      let revision = step.revision;
      let next = null as Awaited<ReturnType<typeof undoSequence>> | null;
      for (let time = 0; time < (step.count ?? 1); time += 1) {
        const expected = { expectedRevision: revision };
        next = await (direction === "undo" ? undoSequence(step.sequence, expected) : redoSequence(step.sequence, expected));
        revision = next.revision;
      }
      return next as Awaited<ReturnType<typeof undoSequence>>;
    };
    void replay()
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
    //: 连着画布的那一步:画布回去,时间线也撤。
    if (typeof step !== "object" || step.canvas !== undefined) restore(next.present);
    if (typeof step === "object") replaySequence(step, "undo");
  }, [restore, replaySequence]);

  const stepForward = React.useCallback(() => {
    const current = historyRef.current;
    const next = redo(current);
    if (!next) return;
    historyRef.current = next;
    setHistory(next);
    const step = current.future[0];
    if (typeof step !== "object" || step.canvas !== undefined) restore(next.present);
    if (typeof step === "object") replaySequence(step, "redo");
  }, [restore, replaySequence]);

  return { history, adopt, flush, stepBack, stepForward };
}
