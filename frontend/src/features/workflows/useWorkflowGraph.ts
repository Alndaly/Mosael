import React from "react";
import { useStore } from "zustand";
import type { Edge, Node } from "@xyflow/react";

import type { Workflow, WorkflowGraph, WorkflowNodeType } from "@/api/client";
import type { useI18n } from "@/app/preferences";
import {
  graphAtScope,
  parseScopeId,
  scopeContainer,
  scopeId,
  scopeIds,
  scopeVariables as scopeVariablesOf,
  withGraphAtScope,
  type ScopePath,
} from "@/features/workflows/scope";
import { createWorkflowGraphStore, type GraphUpdater, type SetGraphOptions } from "@/features/workflows/workflowGraphStore";
import { toWorkflowFlowEdges, toWorkflowFlowNodes } from "@/features/workflows/workflowCanvasModel";
import { EMPTY_SCOPE_VARIABLES, isMarkerNode } from "@/features/workflows/workflowViewShared";
import { usePersistentSelection } from "@/lib/usePersistentTab";
import { listenKeys } from "@/lib/shortcuts";

/**
 * 编辑器里「图」的那一半:整张图(zustand + zundo,撤销 / 重做)、正在编辑的是哪一层、
 * React Flow 的节点和边、选中态,以及把改动写回图的几条路。WorkflowEditor 调它,不另记一份。
 */
export function useWorkflowGraph({
  workflow,
  registry,
  t,
  markerMode,
  markersVisible,
  commentsActive,
}: {
  workflow: Workflow;
  registry: Map<string, WorkflowNodeType>;
  t: ReturnType<typeof useI18n>;
  markerMode: boolean;
  markersVisible: boolean;
  /** 讨论模式开着没有(见 useWorkflowComments)。换模式时画布上的选中一律清掉。 */
  commentsActive: boolean;
}) {
  // graph 是唯一事实(configs/names);放进 zustand+zundo store 拿撤销/重做,React Flow 只管几何与选中。
  // 每个 WorkflowEditor 一个 store(按 workflow.id 重挂),历史不跨工作流。
  const graphStoreRef = React.useRef<ReturnType<typeof createWorkflowGraphStore> | null>(null);
  if (graphStoreRef.current === null) {
    graphStoreRef.current = createWorkflowGraphStore(structuredClone(workflow.graph as unknown as WorkflowGraph));
  }
  const graphStore = graphStoreRef.current;
  /** 整张图:保存、撤销、就绪度分析、运行状态都对着它。 */
  const rootGraph = useStore(graphStore, (s) => s.graph);
  const setRootGraph = useStore(graphStore, (s) => s.setGraph);
  const canUndo = useStore(graphStore.temporal, (s) => s.pastStates.length > 0);
  const canRedo = useStore(graphStore.temporal, (s) => s.futureStates.length > 0);

  // ── 正在编辑哪一层:主流程,或钻进去的循环 / 子图体(见 scope.ts)。
  // **记在本地** —— 用户正在体里编辑,刷新一下被弹回主流程,还得再点进去找刚才那处。
  // 存的路径每次对着当前图校验:那一层没了(容器被删、被撤销掉)就回到主流程。
  // key 按工作流分,免得 A 里记下的节点 id 跑去 B 里生效。
  const scopeCandidates = React.useMemo(() => scopeIds(rootGraph, registry), [rootGraph, registry]);
  const [storedScope, setStoredScope] = usePersistentSelection(`workflow-scope:${workflow.id}`, scopeCandidates);
  const scopePath = React.useMemo(() => parseScopeId(storedScope), [storedScope]);
  const scopeKey = scopeId(scopePath);
  const atRoot = scopePath.length === 0;
  const scopeRef = React.useRef(scopePath);
  scopeRef.current = scopePath;
  const enterScope = React.useCallback(
    (path: ScopePath) => setStoredScope(path.length > 0 ? scopeId(path) : null),
    [setStoredScope],
  );
  /** 画布上这一层的图。下面的编辑逻辑(连线、删除、添加、复制粘贴、折叠)全都对着它,
   *  不知道也不需要知道自己在第几层。 */
  const graph = React.useMemo(
    () => graphAtScope(rootGraph, scopePath, registry) ?? rootGraph,
    [rootGraph, scopePath, registry],
  );
  const scopeNode = React.useMemo(() => scopeContainer(rootGraph, scopePath, registry), [rootGraph, scopePath, registry]);
  /** 体里能引用的虚拟变量:容器在运行时注入的 `{{loop.*}}` / `{{input.*}}`,按后端声明的 body_scope 给(见 scope.ts)。 */
  const scopeVariables = React.useMemo(
    () => (scopeNode ? scopeVariablesOf(scopeNode, registry) : EMPTY_SCOPE_VARIABLES),
    [scopeNode, registry],
  );
  /** 写这一层:把新的这层放回整张图。撤销的合并、脏标记、自动保存因此照旧只有一套。 */
  const setGraph = React.useCallback(
    (updater: GraphUpdater, options?: SetGraphOptions) => {
      setRootGraph((root) => {
        const path = scopeRef.current;
        const scoped = graphAtScope(root, path, registry);
        if (!scoped) return root;
        const next = typeof updater === "function" ? updater(scoped) : updater;
        return next === scoped ? root : withGraphAtScope(root, path, next, registry);
      }, options);
    },
    [setRootGraph, registry],
  );
  //: start 唯一,而且只在主流程里 —— 体的入口是容器节点注入的 {{loop.*}} / {{input.*}}。
  const canAddStart = atRoot && !rootGraph.nodes.some((node) => node.type === "start");
  const [nodes, setNodes] = React.useState<Node[]>(() => toWorkflowFlowNodes(graph, registry));
  const [edges, setEdges] = React.useState<Edge[]>(() => toWorkflowFlowEdges(graph, t, registry));
  // 换了一层,画布节点整份换成那一层的。在渲染中对齐而不是用 effect:effect 慢一帧,
  // 新那层的 React Flow 会先拿着上一层的节点挂载、定位一次。
  const [flowScope, setFlowScope] = React.useState(scopeKey);
  if (flowScope !== scopeKey) {
    setFlowScope(scopeKey);
    setNodes(toWorkflowFlowNodes(graph, registry));
    setEdges(toWorkflowFlowEdges(graph, t, registry));
  }
  React.useEffect(() => { setNodes(current => current.map(node => ({ ...node, selected: false }))); }, [markerMode, markersVisible, commentsActive]);
  /**
   * 检查器开给谁,**从 React Flow 的选中态派生**,不另记一份。
   *
   * 此前检查器自己存一个 selectedNodeId,再靠 selectInspectorNode「同一个动作更新两边」来对齐 ——
   * 但选中态还有别的入口是 React Flow 自己改的:⌘/Ctrl 点击往选区里加、拖动一个没选中的节点、
   * 框选。前者被节点点击回调里的「只选这一个」当场冲掉(⌘ 点击多选根本用不了),后两者让检查器
   * 挂在 A 上而紫框在 B 上。一份事实就没有对齐问题:恰好选中一个 = 编辑它;选中多个 = 在
   * 操作一组(折叠为子图),不是在编辑某一个。
   */
  const selectedFlowIds = React.useMemo(
    () => nodes.filter((node) => node.selected && !isMarkerNode(node)).map((node) => node.id),
    [nodes],
  );
  const selectedNodeId = selectedFlowIds.length === 1 ? selectedFlowIds[0] : null;
  const [dirty, setDirty] = React.useState(false);

  /** 用新图重建画布节点,**保留 React Flow 的选中态**。
   *
   *  这条必须只有一处实现:重建节点的路径有三条(本地编辑走 applyGraph,服务端回传走同步
   *  effect,撤销/重做走 syncFromGraph),每条都会把 selection 冲掉。第一次只修了第一条,于是
   *  "拖完节点过一会儿焦点自己没了"又冒了出来 —— 拖动触发的自动保存回来走的是第二条。
   *  检查器跟着选中态走,所以冲掉选中 = 撤销一下检查器就关了。 */
  const rebuildNodes = React.useCallback(
    (next: WorkflowGraph) =>
      setNodes((current) => {
        const selectedIds = new Set(current.filter((node) => node.selected).map((node) => node.id));
        return toWorkflowFlowNodes(next, registry).map((node) =>
          selectedIds.has(node.id) ? { ...node, selected: true } : node,
        );
      }),
    [registry],
  );
  // 撤销/重做:temporal 改的是 store.graph,再从新 graph 重建 React Flow 的 nodes/edges。
  const syncFromGraph = React.useCallback(() => {
    const root = graphStore.getState().graph;
    // 这一层被撤销掉了(比如撤销的正是「添加这个循环」)就先按整张图画 —— 路径校验随后把画布带回主流程。
    const next = graphAtScope(root, scopeRef.current, registry) ?? root;
    rebuildNodes(next);
    setEdges(toWorkflowFlowEdges(next, t, registry));
    setDirty(true);
  }, [graphStore, registry, rebuildNodes]);
  const undo = React.useCallback(() => {
    if (graphStore.temporal.getState().pastStates.length === 0) return;
    graphStore.temporal.getState().undo();
    syncFromGraph();
  }, [graphStore, syncFromGraph]);
  const redo = React.useCallback(() => {
    if (graphStore.temporal.getState().futureStates.length === 0) return;
    graphStore.temporal.getState().redo();
    syncFromGraph();
  }, [graphStore, syncFromGraph]);

  // Cmd/Ctrl+Z 撤销,Cmd+Shift+Z / Ctrl+Y 重做;输入框 / 代码编辑器(contenteditable)内不劫持。
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey)) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      const key = event.key.toLowerCase();
      if (key === "z" && !event.shiftKey) {
        event.preventDefault();
        undo();
      } else if ((key === "z" && event.shiftKey) || key === "y") {
        event.preventDefault();
        redo();
      }
    };
    return listenKeys(window, onKey);
  }, [undo, redo]);

  const applyGraph = React.useCallback(
    (next: WorkflowGraph, options?: SetGraphOptions) => {
      setGraph(next, options);
      rebuildNodes(next);
      setEdges(toWorkflowFlowEdges(next, t, registry));
      setDirty(true);
    },
    [rebuildNodes],
  );

  return {
    graphStore,
    rootGraph,
    setRootGraph,
    canUndo,
    canRedo,
    scopePath,
    scopeKey,
    atRoot,
    scopeRef,
    enterScope,
    graph,
    scopeNode,
    scopeVariables,
    setGraph,
    canAddStart,
    nodes,
    setNodes,
    edges,
    setEdges,
    selectedFlowIds,
    selectedNodeId,
    dirty,
    setDirty,
    rebuildNodes,
    undo,
    redo,
    applyGraph,
  };
}

export type WorkflowGraphState = ReturnType<typeof useWorkflowGraph>;
