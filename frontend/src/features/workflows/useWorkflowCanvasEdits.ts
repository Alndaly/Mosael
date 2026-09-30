import React from "react";
import { useMutation } from "@tanstack/react-query";
import { applyEdgeChanges, applyNodeChanges, type Connection, type Edge, type EdgeChange, type NodeChange, type ReactFlowInstance } from "@xyflow/react";
import { toast } from "sonner";

import { importAsset, type WorkflowGraph, type WorkflowNodeType } from "@/api/client";
import type { useI18n } from "@/app/preferences";
import { centerCanvasViewport } from "@/components/app/fitCanvasViewport";
import type { CanvasViewportInsets } from "@/components/app/fitCanvasViewport";
import { MARKER_PREFIX, MAX_MARKERS, newMarkerId, nextMarkerName, type CanvasMarker } from "@/features/markers/markers";
import { useMarkerShortcuts } from "@/features/markers/useMarkerShortcuts";
import { pasteNodes, type NodeClip } from "@/features/workflows/clipboard";
import { collapseToSubgraph } from "@/features/workflows/collapse";
import type { DependencySpec } from "@/features/nodeForms/dependents";
import { isDataConnection, isDuplicateControlEdge, withDataInputBound } from "@/features/workflows/connections";
import type { WorkflowGraphState } from "@/features/workflows/useWorkflowGraph";
import { toWorkflowFlowEdges, toWorkflowFlowNodes } from "@/features/workflows/workflowCanvasModel";
import { isMarkerNode } from "@/features/workflows/workflowViewShared";
import { isMediaFile, useFileDrop } from "@/lib/useFileDrop";
import { leaveClipboardToSystem, listenKeys } from "@/lib/shortcuts";

/**
 * 编辑器里「在画布上改图」的那些动作:标记、折叠为子图、复制粘贴、拖动 / 删除 / 连线、
 * 添加节点、把文件拖进画布。都对着**当前这一层**的图(见 useWorkflowGraph)。
 */
export function useWorkflowCanvasEdits({
  graph,
  setGraph,
  applyGraph,
  registry,
  t,
  nodes,
  setNodes,
  setEdges,
  setDirty,
  canAddStart,
  selectedFlowIds,
  selectInspectorNode,
  focusPosition,
  rfRef,
  canvasSurfaceRef,
  getCanvasInsets,
  workspaceId,
}: Pick<
  WorkflowGraphState,
  "graph" | "setGraph" | "applyGraph" | "nodes" | "setNodes" | "setEdges" | "setDirty" | "canAddStart" | "selectedFlowIds"
> & {
  registry: Map<string, WorkflowNodeType>;
  t: ReturnType<typeof useI18n>;
  selectInspectorNode: (nodeId: string | null) => void;
  focusPosition: (x: number, y: number, duration?: number, size?: { width: number; height: number }) => void;
  rfRef: React.MutableRefObject<ReactFlowInstance | null>;
  canvasSurfaceRef: React.MutableRefObject<HTMLDivElement | null>;
  getCanvasInsets: () => CanvasViewportInsets;
  workspaceId: string;
}) {
  // ── 标记(位置书签)────────────────────────────────────────────────────────
  //: 一张几十个节点的图铺开之后,回到"上次在改的那块"要靠拖和缩放。标记把它变成按一下键。
  //: 它住在 graph.markers 里(不是 nodes)—— 它不执行、不连线,进了 nodes 就要有节点类型,
  //: 而运行时会在"未知节点类型"上失败。
  const markers = React.useMemo<CanvasMarker[]>(() => graph.markers ?? [], [graph.markers]);

  const patchMarker = React.useCallback(
    (next: CanvasMarker) => {
      // 改名是"一串输入",在历史里塌成一条(和节点重命名同一套);换快捷键是离散的一步。
      const typing = markers.find((one) => one.id === next.id)?.name !== next.name;
      applyGraph(
        { ...graph, markers: markers.map((one) => (one.id === next.id ? next : one)) },
        { coalesce: typing ? `marker:${next.id}.name` : undefined },
      );
    },
    [graph, markers, applyGraph],
  );

  const deleteMarker = React.useCallback(
    (id: string) => {
      applyGraph({ ...graph, markers: markers.filter((one) => one.id !== id) });
    },
    [graph, markers, applyGraph],
  );

  /**
   * 跳到某个标记:视口居中过去,不改选中态 —— 跳转是"我要看那儿",不是"我要改那个"。
   *
   * **不走 focusPosition。** 那条给的是"选中一个节点"的取景:它会为节点底下的检查器面板
   * 空出两百来像素,而跳到标记时并没有面板打开 —— 借它的话旗子会稳定地偏在画面上方。
   */
  const jumpToMarker = React.useCallback(
    (marker: CanvasMarker) => {
      const instance = rfRef.current;
      const surface = canvasSurfaceRef.current;
      if (!instance || !surface) return;
      void centerCanvasViewport(
        instance,
        surface,
        // 加半枚旗子:节点坐标是左上角,照它居中的话旗子整个偏在右下。
        { x: marker.x + 60, y: marker.y + 14 },
        getCanvasInsets(),
        { zoom: Math.max(instance.getZoom(), 0.6), duration: 350 },
      );
    },
    [getCanvasInsets],
  );

  useMarkerShortcuts(markers, jumpToMarker);

  /** 在当前视口中心插一枚标记 —— 标记标的是"我现在在看的这块地方"。 */
  const addMarker = React.useCallback((point?: { x: number; y: number }) => {
    if (markers.length >= MAX_MARKERS) {
      toast.error(t("markerLimit").replace("{n}", String(MAX_MARKERS)));
      return;
    }
    const instance = rfRef.current;
    const surface = canvasSurfaceRef.current;
    if (!instance || !surface) return;
    const rect = surface.getBoundingClientRect();
    const center = point ?? instance.screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
    applyGraph({
      ...graph,
      markers: [
        ...markers,
        { id: newMarkerId(markers), name: nextMarkerName(t("markers"), markers), x: Math.round(center.x), y: Math.round(center.y) },
      ],
    });
  }, [graph, markers, applyGraph, t]);

  // 框选 → 折叠为子图(ComfyUI 式):把选中节点收进一个 subgraph 节点,进出边界的引用/数据边自动重写。
  const handleCollapse = React.useCallback(
    (ids: string[]) => {
      const res = collapseToSubgraph(graph, ids, registry, { name: t("wfSubgraphBody") });
      if (!res.ok) {
        const description =
          res.reason === "start"
            ? t("wfCollapseErrStart")
            : res.reason === "not-convex"
              ? t("wfCollapseErrNotConvex")
              : res.reason === "condition-branch"
                ? t("wfCollapseErrCondition")
                : t("wfCollapseErrEmpty");
        toast.error(t("wfCollapseFailed"), { description });
        return;
      }
      applyGraph(res.graph);
      selectInspectorNode(res.subgraphId);
      toast.success(t("wfCollapseDone"));
    },
    [graph, registry, applyGraph, selectInspectorNode, t],
  );

  // 节点剪贴板(应用内,按 workflow 编辑器实例存活)。存被选中的节点 + 其内部边,
  // 粘贴时整体换新 id、内部连线原样重连、位置向右下错开。
  const clipboardRef = React.useRef<NodeClip>({ nodes: [], edges: [] });
  const copySelection = React.useCallback((): boolean => {
    // 标记不进剪贴板:它是一个位置书签,粘一份出来只会得到两枚指着同一处的旗子。
    const selectedIds = new Set(nodes.filter((node) => node.selected && !isMarkerNode(node)).map((node) => node.id));
    if (selectedIds.size === 0) return false;
    const pickedNodes = graph.nodes.filter((node) => selectedIds.has(node.id));
    // 只带上"两端都被选中"的边:整段子图连内部接线一起复制,不牵连外部节点。
    const pickedEdges = graph.edges.filter((edge) => selectedIds.has(edge.source) && selectedIds.has(edge.target));
    clipboardRef.current = structuredClone({ nodes: pickedNodes, edges: pickedEdges });
    return true;
  }, [nodes, graph]);
  const pasteClipboard = React.useCallback((): boolean => {
    const pasted = pasteNodes(graph, clipboardRef.current, registry);
    if (!pasted) return false;
    // 让下次 Cmd+V 继续向右下错开,避免层层重叠。
    clipboardRef.current = pasted.clip;
    setGraph(pasted.graph);
    const pastedIds = new Set(pasted.pastedIds);
    // 只让粘贴出来的新节点选中(旧选区取消),方便立刻整体拖走。
    setNodes(toWorkflowFlowNodes(pasted.graph, registry).map((node) => ({ ...node, selected: pastedIds.has(node.id) })));
    setEdges(toWorkflowFlowEdges(pasted.graph, t, registry));
    setDirty(true);
    return true;
  }, [graph, registry]);

  // Cmd/Ctrl+C 复制选中节点,Cmd/Ctrl+V 粘贴,Cmd/Ctrl+G 把选中的折叠成子图;
  // 输入框 / 代码编辑器里不劫持(交给系统复制粘贴)。
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey)) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      const key = event.key.toLowerCase();
      if (key === "c") {
        // 选中了文字就是要复制文字:不拿画布上还选着的节点顶替(见 leaveClipboardToSystem)。
        if (leaveClipboardToSystem(event)) return;
        if (copySelection()) event.preventDefault();
      } else if (key === "v") {
        if (pasteClipboard()) event.preventDefault();
      } else if (key === "g") {
        // G = group,和别处"编组"是同一个键位。**要拦下浏览器的"查找下一个"** ——
        // 不 preventDefault 的话 Safari/Chrome 会在折叠的同时弹出查找栏。
        // 少于两个节点时不接管:那时这个操作本来就不成立,让系统的 ⌘G 照常工作。
        if (selectedFlowIds.length >= 2) {
          event.preventDefault();
          handleCollapse(selectedFlowIds);
        }
      }
    };
    return listenKeys(window, onKey);
  }, [copySelection, pasteClipboard, selectedFlowIds, handleCollapse]);

  const onNodesChange = React.useCallback(
    (changes: NodeChange[]) => {
      setNodes((current) => applyNodeChanges(changes, current));
      // 拖拽会连发几十次 position;声明 coalesce,让这一串在历史里塌成一条(存的是拖之前的
      // 图)。删除是离散操作,不合并 —— 连删两个节点该能分别撤销。
      const dragging = changes.some((change) => change.type === "position");
      // 位置/删除同步回 graph
      setGraph((current) => {
        let next = current;
        for (const change of changes) {
          // 标记住在 graph.markers 里,不在 nodes 里 —— 拖它、删它要落到那一份上去。
          // 走同一条 onNodesChange 是刻意的:拖拽合并、撤销粒度、脏标记因此都是同一套。
          if ("id" in change && change.id.startsWith(MARKER_PREFIX)) {
            const markerId = change.id.slice(MARKER_PREFIX.length);
            if (change.type === "position" && change.position) {
              next = {
                ...next,
                markers: (next.markers ?? []).map((marker) =>
                  marker.id === markerId
                    ? { ...marker, x: Math.round(change.position!.x), y: Math.round(change.position!.y) }
                    : marker,
                ),
              };
            } else if (change.type === "remove") {
              next = { ...next, markers: (next.markers ?? []).filter((marker) => marker.id !== markerId) };
            }
            continue;
          }
          if (change.type === "position" && change.position) {
            next = {
              ...next,
              nodes: next.nodes.map((node) =>
                node.id === change.id ? { ...node, position: { x: change.position!.x, y: change.position!.y } } : node,
              ),
            };
          } else if (change.type === "remove") {
            next = {
              ...next,
              nodes: next.nodes.filter((node) => node.id !== change.id),
              edges: next.edges.filter((edge) => edge.source !== change.id && edge.target !== change.id),
            };
          }
        }
        if (next !== current) setDirty(true);
        return next;
      }, { coalesce: dragging ? "drag" : undefined });
    },
    [],
  );

  const onEdgesChange = React.useCallback((changes: EdgeChange[]) => {
    setEdges((current) => applyEdgeChanges(changes, current));
    setGraph((current) => {
      let next = current;
      for (const change of changes) {
        if (change.type === "remove") {
          next = { ...next, edges: next.edges.filter((edge) => edge.id !== change.id) };
        }
      }
      if (next !== current) setDirty(true);
      return next;
    });
  }, []);
  const onConnect = React.useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      const srcHandle = connection.sourceHandle ?? undefined;
      const tgtHandle = connection.targetHandle ?? undefined;
      // 数据边:输出接点 out:x → 输入接点 in:y。一个输入只接一条数据边;连上后清字面量交给数据边供值。
      if (srcHandle?.startsWith("out:") && tgtHandle?.startsWith("in:")) {
        const output = srcHandle.slice(4);
        const targetInput = tgtHandle.slice(3);
        setGraph((current) => {
          const targetType = current.nodes.find((node) => node.id === connection.target)?.type ?? "";
          const next = withDataInputBound(
            current,
            { targetId: connection.target!, key: targetInput, sourceId: connection.source!, output },
            (registry.get(targetType)?.config ?? {}) as Record<string, DependencySpec>,
          );
          setNodes(toWorkflowFlowNodes(next, registry));
          setEdges(toWorkflowFlowEdges(next, t, registry));
          return next;
        });
        setDirty(true);
        return;
      }
      // 控制边:节点 → 节点(条件分支带 handle)。
      const id = `e-${connection.source}${srcHandle ? `-${srcHandle}` : ""}-${connection.target}`;
      setGraph((current) => {
        if (current.edges.some((edge) => edge.id === id)) return current;
        const next: WorkflowGraph = {
          ...current,
          edges: [
            ...current.edges,
            { id, source: connection.source!, target: connection.target!, source_handle: srcHandle ?? null },
          ],
        };
        setEdges(toWorkflowFlowEdges(next, t, registry));
        return next;
      });
      setDirty(true);
    },
    [registry],
  );

  // 连线合法性:禁自环、禁重复、禁成环(拖到一半就给出红色反馈)。
  const isValidConnection = React.useCallback(
    (connection: Connection | Edge) => {
      const source = connection.source ?? "";
      const target = connection.target ?? "";
      if (!source || !target || source === target) return false;
      const srcHandle = ("sourceHandle" in connection ? connection.sourceHandle : undefined) ?? undefined;
      const tgtHandle = ("targetHandle" in connection ? connection.targetHandle : undefined) ?? undefined;
      // 查重按边的种类分开(见 connections.ts):数据边不存 source_handle,若和控制边混比,
      // 「先连属性再连顺序」会把已有数据边误判成重复而拒掉控制边。数据边去重交给 onConnect 替换。
      if (!isDataConnection(srcHandle, tgtHandle) && isDuplicateControlEdge(graph.edges, source, target, srcHandle)) {
        return false;
      }
      // 从 target 出发能走回 source 即成环
      const adjacency = new Map<string, string[]>();
      for (const edge of graph.edges) {
        adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), edge.target]);
      }
      const queue = [target];
      const seen = new Set<string>();
      while (queue.length) {
        const current = queue.pop()!;
        if (current === source) return false;
        if (seen.has(current)) continue;
        seen.add(current);
        queue.push(...(adjacency.get(current) ?? []));
      }
      return true;
    },
    [graph.edges],
  );

  const addNode = (type: string) => {
    const meta = registry.get(type);
    if (!meta) return;
    if (type === "start" && !canAddStart) return;
    const base = type.replace(/[_.]/g, "-");
    let index = 1;
    while (graph.nodes.some((node) => node.id === `${base}-${index}`)) index += 1;
    const id = type === "start" && !graph.nodes.some((node) => node.id === "start") ? "start" : `${base}-${index}`;
    const maxX = Math.max(0, ...graph.nodes.map((node) => node.position?.x ?? 0));
    const config: Record<string, unknown> = {};
    for (const [key, spec] of Object.entries(meta.config as Record<string, { type?: string }>)) {
      // "graph"(循环体子图)必须种成空图,种成 "" 会让子画布打开时 body.nodes.length 崩掉。
      config[key] = spec?.type === "object" ? {} : spec?.type === "graph" ? { nodes: [], edges: [] } : "";
    }
    const position = { x: maxX + 240, y: 140 + (graph.nodes.length % 3) * 90 };
    const next: WorkflowGraph = {
      ...graph,
      nodes: [...graph.nodes, { id, type, name: meta.label, position, config }],
    };
    applyGraph(next);
    selectInspectorNode(id);
    // 新节点排在最右、又会被右侧检查器盖住 → 加完把视口聚焦过去,别让人找不到。
    // 延后两帧 + 瞬时定位(duration 0):applyGraph 会替换整份节点数组触发重挂重测量,
    // 期间的重渲染会打断 setCenter 的 d3 过渡(动画停在起点=看似没动);瞬时定位无过渡可打断,
    // 一旦落定就不会被后续重渲染重置。
    requestAnimationFrame(() => requestAnimationFrame(() => focusPosition(position.x, position.y, 0)));
  };

  /**
   * 把拖进来的文件上传成素材,并在**鼠标落点**放一个「素材」节点。
   *
   * 落在鼠标那儿而不是排在最右:拖放这个动作本身就指明了位置 —— 把它扔到别处去,
   * 用户得先找一下自己刚拖的东西去哪了。
   *
   * 逐个传而不是并发:一次拖十个视频,并发会把带宽和后端转码队列同时打满,
   * 而用户看到的是十个都卡着不动。
   */
  const dropUpload = useMutation({
    mutationFn: async ({ files, at }: { files: File[]; at: { x: number; y: number } }) => {
      const created: Array<{ id: string; name: string }> = [];
      for (const file of files) {
        const asset = await importAsset({ workspaceId, file });
        created.push({ id: asset.id, name: asset.name });
      }
      return { created, at };
    },
    onSuccess: ({ created, at }) => {
      let next = graph;
      created.forEach((asset, index) => {
        const base = "asset";
        let seq = 1;
        while (next.nodes.some((node) => node.id === `${base}-${seq}`)) seq += 1;
        const id = `${base}-${seq}`;
        next = {
          ...next,
          nodes: [
            ...next.nodes,
            {
              id,
              type: "asset",
              name: asset.name,
              // 多个文件斜着摞开,不然它们会精确重叠成一个。
              position: { x: at.x + index * 24, y: at.y + index * 24 },
              config: { asset_id: asset.id },
            },
          ],
        };
      });
      applyGraph(next);
      toast.success(t("wfDropped").replace("{n}", String(created.length)));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  // React Flow 的坐标换算要在 drop 那一刻做(那时才有鼠标位置),而 useFileDrop 的回调
  // 拿不到事件 —— 用一个 ref 把落点从事件里带出来。
  const pendingDropAt = React.useRef<{ x: number; y: number } | null>(null);
  const canvasDrop = useFileDrop((files) => {
    dropUpload.mutate({ files, at: pendingDropAt.current ?? { x: 120, y: 140 } });
  }, isMediaFile);

  return {
    markers,
    patchMarker,
    deleteMarker,
    jumpToMarker,
    addMarker,
    handleCollapse,
    onNodesChange,
    onEdgesChange,
    onConnect,
    isValidConnection,
    addNode,
    dropUpload,
    pendingDropAt,
    canvasDrop,
  };
}
