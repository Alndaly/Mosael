/**
 * 画板画布的撤销 / 重做,以及「画布变了就汇一份给上层」。从 BoardCanvas 拆出来的钩子。
 *
 * **撤销的一步 = 人做的一件事**(和剪辑那边的「一次手势 = 一条操作」同一条,见 CONTEXT.md):
 *
 *  · 拖、拉大小、在框里打字:手还没松、焦点还在框里,中间停多久都不记,松手 / 离开那个框才记一步(`held`)。
 *  · 不是人做的变化不记成一步,并进当前这一份(`absorb`):媒体加载出来按宽高比校正高度、面板一挂上就补齐的表单默认值、
 *    服务端存回来时纠正的运行态 —— 此前它们各记一步,撤一下「什么都没变」,再撤才撤到人做的那一下;面板挂着时还会
 *    撤一步、面板又补一遍,把重做冲掉。
 *  · 点一次运行(生成、能力)是一步,它落下的占位和产出不管什么时候到都算在这一步里(canvasHistory 的 RunStep、boardRuns)。
 *  · 停手不到 400ms 就按 ⌘Z:先把这一下记成一步再撤 —— 此前这一下没进历史,撤掉的是它前面那一步,它自己丢了。
 */
import React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import type { Edge, Node } from "@xyflow/react";

import type { BoardCanvas as Canvas, BoardItem } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { redoSequence, undoSequence } from "@/api/domains/editor";
import { useI18n } from "@/app/preferences";
import { boardSequenceKey } from "@/features/boards/SequenceCell";
import {
  canvasOf,
  dropRun,
  dropSequenceStep,
  emptyHistory,
  joinSequenceToCanvas,
  record,
  recordRun,
  recordSequence,
  redo,
  retagSequenceStep,
  runOf,
  runsIn,
  sequenceOf,
  undo,
  type History,
  type SequenceStep,
  type Step,
} from "@/features/boards/canvasHistory";
import { onSequenceEdit } from "@/features/boards/sequenceCursor";
import { LAYERS, boardItems, toCanvas, toNodes } from "@/features/boards/boardCanvasModel";
import { withServerOwned } from "@/features/boards/boardServerOwned";
import { rebaseCanvas } from "@/features/boards/boardRebase";
import { claimLanding, newRun, placeRun, runOutputs, type BoardRun } from "@/features/boards/boardRuns";
import { toMarkerNodes } from "@/features/markers/markers";

/** 焦点在这块画布里的一个打字的地方(便签、提示词、名字、面板里的输入框)。 */
function typingInside(root: HTMLElement | null): boolean {
  const active = typeof document === "undefined" ? null : document.activeElement;
  if (!root || !(active instanceof HTMLElement) || !root.contains(active)) return false;
  if (active.isContentEditable || active.tagName === "TEXTAREA") return true;
  return active.tagName === "INPUT" && !/^(checkbox|radio|button|submit|reset|range|color|file|image)$/i.test((active as HTMLInputElement).type);
}

/**
 * 把并进当前这一份的那几格的那几个字段(`absorbed`)照画布此刻的样子写进 `present`。字段的先后照此刻那一格排 ——
 * 撤销栈按 JSON 比对,先后不一样就成了「变了」。`present` 里没有的格子不管(它还没进过历史)。
 */
function absorbInto(present: string, live: Canvas, absorbed: ReadonlyMap<string, ReadonlySet<string>>): string {
  const canvas = JSON.parse(present) as Canvas;
  const now = new Map(live.items.map((item) => [item.id, item]));
  let changed = false;
  const items = canvas.items.map((item) => {
    const keys = absorbed.get(item.id);
    const fresh = now.get(item.id);
    if (!keys || !fresh) return item;
    const merged = { ...item } as unknown as Record<string, unknown>;
    for (const key of keys) {
      if (key in fresh) merged[key] = (fresh as unknown as Record<string, unknown>)[key];
      else delete merged[key];
    }
    const ordered: Record<string, unknown> = {};
    for (const key of Object.keys(fresh)) if (key in merged) ordered[key] = merged[key];
    for (const key of Object.keys(merged)) if (!(key in ordered)) ordered[key] = merged[key];
    changed = true;
    return ordered as unknown as BoardItem;
  });
  return changed ? JSON.stringify({ ...canvas, items }) : present;
}

/** 一轮(`key`)刚收尾:它那一步之后记下的那几份画布(past 里在它后面的、future 里的)都是它还在跑时的样子。 */
function markInFlight(key: string, run: BoardRun, current: History) {
  const at = current.past.findIndex((step) => runOf(step) === key);
  const later: Step[] = at < 0 ? [] : [...current.past.slice(at + 1), ...current.future];
  for (const step of later) {
    const canvas = canvasOf(step);
    if (canvas !== undefined) run.inFlight.add(canvas);
  }
}

export function useBoardHistory({
  nodes,
  edges,
  setNodes,
  setEdges,
  onChange,
  surface,
}: {
  nodes: Node[];
  edges: Edge[];
  setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
  setEdges: React.Dispatch<React.SetStateAction<Edge[]>>;
  onChange: (canvas: Canvas) => void;
  /** 画布的 DOM:焦点在它里面的输入框里时,打的字攒成一步(见 `held`)。 */
  surface: React.RefObject<HTMLElement | null>;
}) {
  const t = useI18n();
  const queryClient = useQueryClient();
  //: 采用服务端那一版时要按 id 找回节点此刻的选中态(见 adopt);回调里读最新的,不进依赖。
  const graph = React.useRef({ nodes, edges });
  graph.current = { nodes, edges };
  const onChangeRef = React.useRef(onChange);
  onChangeRef.current = onChange;

  /**
   * 撤销/重做。存的是**整份画布的快照** —— 画板的事实来源是 React Flow 的 nodes/edges,
   * 撤销就是把某一份装回去(工作流那边挂在 zundo 上,因为它的事实来源是 store 里的 graph)。
   *
   * 事实在 ref 里,state 只是给渲染(撤销键灰不灰)的那一份:撤 / 重做、记一步、时间线回来的那一下都要在同一段同步代码里
   * 读到上一下的结果(先把攒着的记下再撤),setState 的更新函数做不到;放进更新函数里的网络请求,开发模式下还会跑两遍。
   */
  const historyRef = React.useRef<History>(emptyHistory(JSON.stringify(toCanvas(nodes, edges))));
  const [history, setHistory] = React.useState(historyRef.current);
  //: 这一摞里那几次运行落下了什么(见 boardRuns)。键是 RunStep 的 `run`。
  const runs = React.useRef(new Map<string, BoardRun>());
  const runSerial = React.useRef(0);
  const commit = React.useCallback((next: History) => {
    if (next === historyRef.current) return;
    historyRef.current = next;
    //: 摞里没有了的那几轮(重做被新动作清掉、太老被丢掉)不再跟:它们再落下什么,就是服务端落下的。
    const alive = new Set([...runsIn(next.past), ...runsIn(next.future)]);
    for (const key of runs.current.keys()) if (!alive.has(key)) runs.current.delete(key);
    setHistory(next);
  }, []);

  //: 上一次汇给上层的那一份(和历史里存的是同一种写法)。挂上时就是这一份 —— 加载进来不是编辑,不汇。
  const emitted = React.useRef(historyRef.current.present);
  //: 服务端落下、人还没亲手删过、也不是这一摞里哪一步引起的格子(智能体加的、别处或打开之前点的运行交回的):
  //: 撤销 / 重做回到更早的一份时补回去(见 boardServerOwned)。人删了它就归人了 —— 撤销、重做照人的那几步来。
  const landed = React.useRef(new Set<string>());
  //: 等着并进当前这一份的变化:哪一格的哪几个字段(见 absorb)。
  const absorbed = React.useRef(new Map<string, Set<string>>());

  /** 人还在做这一下:拖着、拉着大小,或者焦点在画布里的输入框里。 */
  const held = React.useCallback(
    () => graph.current.nodes.some((node) => node.dragging || node.resizing) || typingInside(surface.current),
    [surface],
  );

  /**
   * 画布变了:**攒一下再序列化一次**,汇给上层(自动保存、查找)和记进撤销历史的是同一份。
   *
   * 此前每一帧都 JSON.stringify 整张画布、再 JSON.parse 一遍交给上层 —— 拖一格,大画板上每帧几毫秒到几十毫秒,
   * 上层还跟着每帧重渲染一次。现在攒到停手 400ms(和撤销的并步是同一个窗口:拖一下是一步)再做一次。
   * **按 JSON 比对**:React Flow 每次拖动都换新对象,选中一格也换 —— 内容没变就不汇、不记。
   * 要服务端照着画布去做的动作(生成、写字)等不了这 400ms,先 `flush()` 拿现在这一份(见 BoardsView.run)。
   * `force`:人还在做这一下也记(点运行、按撤销之前,得先把这之前的那一下落成一步)。
   */
  const settle = React.useCallback((force = false): Canvas => {
    const canvas = toCanvas(graph.current.nodes, graph.current.edges);
    const snapshot = JSON.stringify(canvas);
    if (snapshot !== emitted.current) {
      emitted.current = snapshot;
      onChangeRef.current(canvas);
    }
    let current = historyRef.current;
    if (absorbed.current.size) {
      current = { ...current, present: absorbInto(current.present, canvas, absorbed.current) };
      absorbed.current = new Map();
    }
    if (!force && held()) {
      commit(current);
      return canvas;
    }
    const alive = new Set(canvas.items.map((item) => item.id));
    for (const id of landed.current) if (!alive.has(id)) landed.current.delete(id);
    commit(record(current, snapshot));
    return canvas;
  }, [commit, held]);
  const pending = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const schedule = React.useCallback(() => {
    if (pending.current) clearTimeout(pending.current);
    pending.current = setTimeout(() => {
      pending.current = null;
      settle();
    }, 400);
  }, [settle]);
  React.useEffect(schedule, [nodes, edges, schedule]);
  //: 离开画布里的输入框:那段字攒成的一步这时候记(焦点换走时画布没变,上面那个定时器不会再响)。
  React.useEffect(() => {
    const root = surface.current;
    if (!root) return;
    root.addEventListener("focusout", schedule);
    return () => root.removeEventListener("focusout", schedule);
  }, [surface, schedule]);
  React.useEffect(
    () => () => {
      //: 卸载时把攒着的那一次汇出去 —— 拖完最后一下就切走,自动保存还要把它补上。
      if (pending.current) {
        clearTimeout(pending.current);
        settle(true);
      }
    },
    [settle],
  );
  /** 不等攒够,现在就把画布汇出去,回这一份。`force` 见 settle。 */
  const flush = React.useCallback((force = false): Canvas => {
    if (pending.current) {
      clearTimeout(pending.current);
      pending.current = null;
    }
    return settle(force);
  }, [settle]);

  /**
   * 这一格的这几个字段刚被改成的样子**不是人的一步**,并进当前这一份(媒体宽高比校正、面板补齐的默认值、服务端纠正的
   * 运行态和产出)。调用方自己改节点,这里只记下哪几个字段:下一次攒够时照画布此刻的样子写进 `present`。
   */
  const absorb = React.useCallback((itemId: string, keys: readonly string[]) => {
    const set = absorbed.current.get(itemId) ?? new Set<string>();
    for (const key of keys) set.add(key);
    absorbed.current.set(itemId, set);
  }, []);

  /** 把一份画布装进 React Flow,回它装进去之后序列化出来的样子(和 settle 同一种写法)。节点按 id 留住选中和量过的尺寸。 */
  const load = React.useCallback(
    (canvas: Canvas): string => {
      const before = new Map(graph.current.nodes.map((node) => [node.id, node]));
      const nextNodes = [...toNodes(canvas.items), ...toMarkerNodes(canvas.markers ?? [], LAYERS.marker)].map((node) => {
        const old = before.get(node.id);
        return old ? { ...node, selected: old.selected, measured: old.measured } : node;
      });
      const nextEdges = canvas.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target }));
      setNodes(nextNodes);
      setEdges(nextEdges);
      graph.current = { nodes: nextNodes, edges: nextEdges };
      return JSON.stringify(toCanvas(nextNodes, nextEdges));
    },
    [setNodes, setEdges],
  );

  //: 撤 / 重做装回过几次:面板照它重挂(从装回去的表单重新读,见 BoardCanvas),图片照它重新校正宽高比。
  const [restores, setRestores] = React.useState(0);
  /**
   * 撤 / 重做到 `next`:装回它的那一份,服务端归属的东西照画布此刻的补回去(在跑的、落下的格子和产出),这一摞里那几次
   * 运行照它们那一步在不在效拿下 / 补上(见 boardServerOwned)。`present` 换成装回去之后的样子 —— 撤销自己造成的变化
   * 因此和 present 一样,不会再被记成一步(不然撤一步立刻又记一步,重做就永远回不去了)。
   */
  const restore = React.useCallback(
    (next: History) => {
      const current = toCanvas(graph.current.nodes, graph.current.edges);
      const kept = runsIn(next.past);
      const gone = runsIn(next.future);
      const all = [...runs.current.entries()];
      const inPlay = {
        undone: all.filter(([key]) => gone.has(key)).map(([, run]) => run),
        inFlight: all.filter(([key, run]) => kept.has(key) && run.landed && run.inFlight.has(next.present)).map(([, run]) => run),
      };
      const loaded = load(withServerOwned(JSON.parse(next.present) as Canvas, current, landed.current, inPlay));
      absorbed.current = new Map();
      commit({ ...next, present: loaded });
      setRestores((count) => count + 1);
    },
    [load, commit],
  );

  /**
   * 采用服务端的新一版(回执落地、智能体改了板、保存撞了版本号之后合好的那份),**撤销历史不清空、也不改写**。
   *
   * `canvas` 是已经把本地改动重放上去的那份(boardRebase)。撤销栈里那几份快照原样留着:撤到更早的一份时,服务端
   * 落下的东西在**应用那一份时**补回去(restore → boardServerOwned)—— 撤一步回到的样子里照样有刚出的图,在跑的
   * 一格也撤不成空槽。此前每采用一次就把整摞快照按它合一遍:慢(100 份 × 1000 格约一秒),还合错。
   *
   * 新落下的格子先认给这一摞里还没收尾的那几次运行(boardRuns.claimLanding);认不走的才是「服务端落下的」。
   * 节点按 id 就地换:选中、量出来的尺寸留着 —— 回执每落一次选中的那一格就被取消选中,面板就收起来了。
   *
   * `sync`:合出 `canvas` 的那两版服务端画布(上一次认下的、这一次的)。人正做到一半(打字、拖着)时,当前这一份
   * 不换成合好的那份(里面有他还没做完的那一下),而是把服务端这一次的变化合到**上一次记下的那份**上 —— 做完时记的
   * 那一步就只是他做的那一下。不然打着字落下一张图,这段字要撤两下。
   */
  const adopt = React.useCallback(
    (canvas: Canvas, sync?: { base: Canvas; fresh: Canvas }) => {
      const midway = sync && held() ? rebaseCanvas(sync.base, JSON.parse(historyRef.current.present) as Canvas, sync.fresh).canvas : null;
      const before = new Map(boardItems(graph.current.nodes).map((item) => [item.id, item]));
      const open = [...runs.current.entries()].filter(([, run]) => !run.landed);
      claimLanding(open.map(([, run]) => run), before, canvas);
      //: 这一摞里那几次运行的格子:宿主(就地填进来的是它那一轮的产出)和认下的新格子(一次多张的占位这一版才收下产出)。
      const ours = new Set([...runs.current.values()].flatMap((run) => [run.host, ...run.items.keys()]));
      //: 记下服务端这一版落下的(不是哪一次运行的):本地没有的新格子,和产出刚落进来的那一格。
      for (const item of canvas.items) {
        if (ours.has(item.id)) continue;
        const was = before.get(item.id);
        const output = Boolean(item.asset_id) && item.run?.status === "succeeded" && was?.asset_id !== item.asset_id;
        if (!was || output) landed.current.add(item.id);
      }
      const snapshot = load(canvas);
      absorbed.current = new Map();
      const current = { ...historyRef.current, present: midway ? JSON.stringify(midway) : snapshot };
      //: 这一版里收尾的那几轮:这一步之后、此刻之前记下的那几份都是它还在跑时的样子。
      for (const [key, run] of open) if (run.landed) markInFlight(key, run, current);
      commit(current);
    },
    [load, commit, held],
  );

  /**
   * 点了一次运行(生成、写字、念、截、一项能力):先把这之前攒着的记成一步,再记这一次 —— 它落下的东西都算在这一步里。
   * 回这一次的记号,请求回来时交给 `placed`。
   */
  const beginRun = React.useCallback(
    (hostId: string): string => {
      flush(true);
      runSerial.current += 1;
      const key = `run-${runSerial.current}`;
      runs.current.set(key, newRun(hostId));
      commit(recordRun(historyRef.current, key));
      return key;
    },
    [flush, commit],
  );
  /** 那次运行的请求回来了:`canvas` 是服务端回的那一版,没跑起来是 null(这一步什么都没做,拿掉)。 */
  const placed = React.useCallback(
    (key: string, canvas: Canvas | null) => {
      const run = runs.current.get(key);
      if (!run) return;
      if (!canvas) {
        runs.current.delete(key);
        commit(dropRun(historyRef.current, key));
        return;
      }
      const local = boardItems(graph.current.nodes).find((item) => item.id === run.host);
      placeRun(run, canvas.items.find((item) => item.id === run.host), local);
      if (run.landed) markInFlight(key, run, historyRef.current);
    },
    [commit],
  );

  //: 时间线格里做成的一步记进这摞(见 canvasHistory 的「时间线的一步」)。连一根线进时间线格引起的那一步,和画布上
  //: 那根线并成一步:先把攒着的画布变化记下(线已经在画布上了),再把两步并起来。
  React.useEffect(
    () =>
      onSequenceEdit((sequenceId, revision, link) => {
        if (link) flush(true);
        const current = historyRef.current;
        commit((link && joinSequenceToCanvas(current, sequenceId, revision, link)) || recordSequence(current, sequenceId, revision));
      }),
    [flush, commit],
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
        commit(retagSequenceStep(historyRef.current, where, next.revision));
      })
      .catch((error: unknown) => {
        commit(dropSequenceStep(historyRef.current, where));
        toast.error(errorText(error));
      });
  }, [queryClient, commit]);

  /** 退 / 进一步:装回那一份(带着画布的那几种步),时间线的一步调那条时间线自己的撤 / 重做。 */
  const step = React.useCallback(
    (direction: "undo" | "redo") => {
      //: 停手不到 400ms 就按的:先把那一下记成一步,撤的就是它。
      flush(true);
      const current = historyRef.current;
      const taken = direction === "undo" ? current.past.at(-1) : current.future[0];
      if (taken === undefined) return;
      const key = runOf(taken);
      const run = key ? runs.current.get(key) : undefined;
      //: 还在跑的那一轮撤不动(ADR 0025):任务照跑、钱照花。等它收尾,或者在格子上停下。
      if (direction === "undo" && run && !run.landed) {
        toast.message(t("boardUndoRunning"));
        return;
      }
      const next = direction === "undo" ? undo(current) : redo(current);
      if (!next) return;
      if (canvasOf(taken) !== undefined) restore(next);
      else commit(next);
      const sequence = sequenceOf(taken);
      if (sequence) replaySequence(taken as SequenceStep, direction);
      //: 撤下了一轮运行的产出:说一声 —— 素材、笔记还在各自的库里,重做放得回来。
      if (direction === "undo" && run) {
        const { count, assets } = runOutputs(run);
        if (count > 0) toast.message(t(assets ? "boardUndoRunAssets" : "boardUndoRunOutputs").replace("{n}", String(count)));
      }
    },
    [flush, restore, commit, replaySequence, t],
  );
  const stepBack = React.useCallback(() => step("undo"), [step]);
  const stepForward = React.useCallback(() => step("redo"), [step]);

  return { history, adopt, flush, absorb, beginRun, placed, restores, stepBack, stepForward };
}
