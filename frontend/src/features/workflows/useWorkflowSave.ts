import React from "react";
import { type QueryClient, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  ApiError,
  getWorkflow,
  tasksAwaitingApprovalKey,
  updateWorkflow,
  type Workflow,
  type WorkflowGraph,
  type WorkflowNodeType,
} from "@/api/client";
import type { useI18n } from "@/app/preferences";
import { graphAtScope } from "@/features/workflows/scope";
import { syncFromServer } from "@/features/workflows/serverSync";
import type { WorkflowGraphState } from "@/features/workflows/useWorkflowGraph";
import { toWorkflowFlowEdges } from "@/features/workflows/workflowCanvasModel";
import { createWriteQueue, sameContent } from "@/lib/optimisticWrites";

/**
 * 编辑器和服务端之间的那一半:跟进服务端的新版本、自动保存(带 CAS 底子)、撞了 409 换成服务端那份、
 * 离开时把欠着的那次存掉。
 */
export function useWorkflowSave({
  workflow,
  workspaceId,
  qc,
  t,
  registry,
  graphStore,
  setRootGraph,
  scopeRef,
  rebuildNodes,
  setEdges,
  graph,
  dirty,
  setDirty,
  dragging,
  selectInspectorNode,
}: Pick<
  WorkflowGraphState,
  "graphStore" | "setRootGraph" | "scopeRef" | "rebuildNodes" | "setEdges" | "graph" | "dirty" | "setDirty"
> & {
  workflow: Workflow;
  workspaceId: string;
  qc: QueryClient;
  t: ReturnType<typeof useI18n>;
  registry: Map<string, WorkflowNodeType>;
  /** 正在拖节点:这时不自动保存,松手后再存(见下面那条 effect)。 */
  dragging: boolean;
  selectInspectorNode: (nodeId: string | null) => void;
}) {
  // 智能体经确认卡改图后 updated_at 变化:画布无本地改动时自动跟进服务端版本。
  const lastSyncedRef = React.useRef(workflow.updated_at);
  // 自己保存引发的那次 refetch 不能重建画布(重建会丢掉 React Flow 的实测尺寸、造成闪烁与
  // 拖拽中断)。认的是**图的摘要**(见 serverSync 的 ours):智能体在保存回来之前改的那一版不是我们的。
  const selfSaveRef = React.useRef<readonly string[]>([]);
  /**
   * 服务端确认过的那一份,和它的摘要(下一次保存的底子)。**两者是一个单位**:只换其一的话,
   * 一份旧画布会拿着新底子通过 CAS,把别人的改动静默盖掉 —— 和画板的 revision + confirmedCanvas
   * 同一条。本地这份跟服务端那份不是同一个对象(自己存完不拿回传的图重建画布),所以记的是
   * **发出去的那份本地图**。
   */
  const confirmedRef = React.useRef<{ graph: WorkflowGraph; hash: string }>({
    graph: graphStore.getState().graph,
    hash: workflow.graph_hash,
  });

  React.useEffect(() => {
    const { action, next: synced } = syncFromServer(
      { accounted: lastSyncedRef.current, ours: selfSaveRef.current },
      { updatedAt: workflow.updated_at, graphHash: workflow.graph_hash, dirty },
    );
    lastSyncedRef.current = synced.accounted;
    selfSaveRef.current = synced.ours;
    if (action !== "apply") return;
    const next = structuredClone(workflow.graph as unknown as WorkflowGraph);
    setRootGraph(next);
    //: 画布换成了这一份,底子也跟着换 —— 两者是一个单位(见下面的 confirmedRef)。
    confirmedRef.current = { graph: next, hash: workflow.graph_hash };
    const scoped = graphAtScope(next, scopeRef.current, registry) ?? next;
    rebuildNodes(scoped);
    setEdges(toWorkflowFlowEdges(scoped, t, registry));
    //: 撤销历史一并清掉,理由同 adoptServerWorkflow:历史里记的是跟进之前那份本地图,按一下撤销
    //: 就把它写回画布,而自动保存会带着刚换上的新底子通过 CAS —— 智能体的改动被静默盖掉。
    graphStore.temporal.getState().clear();
  }, [workflow.updated_at, workflow.graph, workflow.graph_hash, dirty, rebuildNodes]);

  /**
   * 换成服务端的这一份:版本历史里恢复了一版,或者保存撞了 409。
   *
   * 撤销历史一并清掉 —— 它记的是被换掉的那份本地图,留着的话按一下撤销就把旧图又写回去,
   * 而下一次自动保存会带着新底子把它存上:等于绕过冲突检查,把别人的改动静默盖掉。
   */
  const adoptServerWorkflow = React.useCallback(
    (saved: Workflow) => {
      const next = structuredClone(saved.graph as unknown as WorkflowGraph);
      confirmedRef.current = { graph: next, hash: saved.graph_hash };
      setRootGraph(next);
      const scoped = graphAtScope(next, scopeRef.current, registry) ?? next;
      rebuildNodes(scoped);
      setEdges(toWorkflowFlowEdges(scoped, t, registry));
      graphStore.temporal.getState().clear();
      selectInspectorNode(null);
      //: 这一版已经铺在画布上了:它随 props 到达时认下、不再重建。**不提前写 lastSyncedRef** ——
      //: props 这会儿还是旧的,写了的话紧接着那一轮会把旧 props 当成「服务端又变了」铺回来
      //: (同自动保存那条,见 serverSync)。认的是这一份的摘要;之前自己存的那几版已经被它越过了。
      selfSaveRef.current = [saved.graph_hash];
      pendingSaveRef.current = false;
      setDirty(false);
      //: 列表缓存(这个编辑器的 props 从那来)当场换成这一份。只等下一次轮询的话,紧接着那一轮
      //: 渲染看到的还是旧 props,同步 effect 会把旧图(连同旧底子)又铺回画布。
      qc.setQueryData<Workflow[]>(["workflows", workspaceId], (list) =>
        list?.map((one) => (one.id === saved.id ? saved : one)),
      );
    },
    [graphStore, qc, rebuildNodes, registry, selectInspectorNode, setRootGraph, t, workspaceId],
  );
  //: 这张图上的写请求排成一队,各自轮到时才读画布和底子(见 lib/optimisticWrites)。各发各的话,
  //: 上一次保存还在路上时又改了一处,两次带着**同一个**底子出门 —— 后到的那次撞上自己。
  const [serially] = React.useState(createWriteQueue);
  const save = useMutation({
    mutationFn: () =>
      serially(async () => {
        //: 发的是**轮到它时**画布上的那一份,不是排队那一刻的。
        const sent = graphStore.getState().graph;
        if (sameContent(sent, confirmedRef.current.graph)) return { sent, saved: null };
        try {
          const saved = await updateWorkflow(workflow.id, { graph: sent, base_graph_hash: confirmedRef.current.hash });
          confirmedRef.current = { graph: sent, hash: saved.graph_hash };
          return { sent, saved };
        } catch (error) {
          //: 冲突在**队列里**收拾完:排在后面的那次轮到时,画布和底子已经是服务端那份了,
          //: 不会拿着同一个旧底子再撞一次、再弹一次。
          if (error instanceof ApiError && error.status === 409) {
            adoptServerWorkflow(await getWorkflow(workflow.id));
            toast.error(t("wfSaveConflict"), { description: t("wfSaveConflictDetail") });
          }
          throw error;
        }
      }),
    onSuccess: ({ sent, saved }) => {
      //: 存的途中又改了一处的话,那一处还欠着:dirty 不能跟着这次一起清掉。
      if (graphStore.getState().graph === sent) setDirty(false);
      if (!saved) return;
      // 自己存的这一版一会儿会随重新拉取回来。标一下,让同步 effect 认下它而**不重建画布** ——
      // 重建会丢掉 React Flow 量好的尺寸,节点有一帧是 visibility:hidden;那一帧里抓节点会抓到
      // 画布上变成平移,而自动保存每次编辑都跑,于是节点一直"抓不住"。
      //
      // **这里不写 lastSyncedRef。** 它的含义是「我们在 props 上见过的那一版」,而 props 这会儿
      // 还是旧的。提前写成 saved.updated_at 会让紧接着那一轮(setDirty 引起的重渲染)看到
      // 「旧 ≠ 新」,把这张底牌当场用掉 —— 等真正的新版本回来时已经没人挡着了。见 serverSync。
      //
      // 记的是这一版的摘要,不是「下一版是我们的」:保存回来之前智能体改了图的话,先到的是它那一版。
      selfSaveRef.current = [...selfSaveRef.current, saved.graph_hash];
      void qc.invalidateQueries({ queryKey: ["workflows", workspaceId] });
      // 纯布局保存不会成版，也不需要重拉历史；执行语义变化时才同步版本面板。
      if (saved.revision !== workflow.revision) {
        void qc.invalidateQueries({ queryKey: ["workflow-revisions", workflow.id] });
        //: 新的一版可能让别人的定时任务停下等主人认可(ADR 0047):画布上那条提醒跟着刷新。
        void qc.invalidateQueries({ queryKey: tasksAwaitingApprovalKey(workflow.id) });
      }
    },
    onError: (error: Error) => {
      if (error instanceof ApiError && error.status === 409) return; // 已在队列里载入服务端那份并告知
      toast.error(t("wfSaveFailed"), { description: error.message });
    },
  });
  // Real-time save (Dify-style): debounce-save the graph whenever it changes, so there's no
  // manual "save" step. A save clears `dirty`; a rapid edit reschedules the pending save.
  const saveRef = React.useRef(save);
  saveRef.current = save;
  // Whether a save is still owed, read by the unmount flush below. A ref, not state, because
  // the cleanup that reads it runs after the last render.
  const pendingSaveRef = React.useRef(false);
  pendingSaveRef.current = dirty;

  React.useEffect(() => {
    if (!dirty || dragging) return;
    const id = window.setTimeout(() => saveRef.current.mutate(), 700);
    return () => window.clearTimeout(id);
  }, [dirty, graph, dragging]);

  // Flush on the way out. The debounce timer is cleared by its own cleanup, so editing a node
  // and then switching workflow, leaving the view, or closing the window inside 700ms threw the
  // edit away — and the 5s poll then repainted the canvas from the server's older graph, so it
  // looked as though the change had undone itself. This editor is keyed by workflow id, so
  // switching workflows unmounts it and is the common way to hit that.
  React.useEffect(() => {
    const flush = () => {
      if (pendingSaveRef.current) saveRef.current.mutate();
    };
    window.addEventListener("beforeunload", flush);
    return () => {
      window.removeEventListener("beforeunload", flush);
      flush();
    };
  }, []);

  return { save, pendingSaveRef, adoptServerWorkflow };
}

export type WorkflowSaveState = ReturnType<typeof useWorkflowSave>;
