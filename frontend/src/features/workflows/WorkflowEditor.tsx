import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Background,
  ConnectionLineType,
  MiniMap,
  Panel,
  ReactFlow,
  type ReactFlowInstance,
} from "@xyflow/react";
import { Boxes, FileUp, History, Loader2 } from "lucide-react";
import { toast } from "sonner";

import {
  deleteWorkflow,
  exportWorkflowFile,
  updateWorkflow,
  type Workflow,
  type WorkflowGraph,
  type WorkflowNodeType,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { AnnotationModeHint } from "@/features/markers/AnnotationModeHint";
import { useCanvasInputMode, canvasWheelProps } from "@/components/app/canvasInputMode";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { CANVAS_GLASS_SURFACE_CLASS, canvasDockedPanelEdges, canvasRightDockOcclusion } from "@/components/app/canvasPanelLayout";
import { canvasInsets, centerCanvasViewport, fitCanvasViewport, visibleCanvasSize } from "@/components/app/fitCanvasViewport";
import { RightDockResizeHandle } from "@/components/app/RightDockResizeHandle";
import { useEdgeShape } from "@/components/app/canvasEdgeShape";
import { CANVAS_EDGE_CLASS } from "@/components/app/canvasEdges";
import type { CanvasSearchHighlight } from "@/components/app/CanvasNodeSearch";
import { blurFloatingPanels } from "@/components/app/useFloatingPanel";
import { useCanvasDeleteKey } from "@/components/app/useCanvasDeleteKey";
import { usePageTrail } from "@/components/layout/pageTrail";
import { Button } from "@/components/ui/button";
import { Hint } from "@/components/ui/tooltip";
import { CanvasAgentChat, type CanvasAgentMode } from "@/features/agent/CanvasAgentChat";
import { CollaborationSheet } from "@/features/collaboration/CollaborationSheet";
import { MarkerEditorProvider } from "@/features/markers/MarkerEditorProvider";
import { useNodePicker } from "@/features/nodeForms/nodePicker";
import { NodeInspector } from "@/features/workflows/NodeInspector";
import { WORKFLOW_CANVAS_EDGE_TYPES } from "@/features/workflows/ReferenceHintEdge";
import { useReferenceHintEdges } from "@/features/workflows/referenceHints";
import { highlightAtLayer, nodeSearchEntryId, nodeSearchTargets } from "@/features/workflows/nodeSearch";
import { bodyKey, scopeContainer, scopeId } from "@/features/workflows/scope";
import { useCanvasPosture } from "@/features/workflows/useCanvasPosture";
import { useWorkflowCanvasEdits } from "@/features/workflows/useWorkflowCanvasEdits";
import { useWorkflowDisplayEdges, useWorkflowDisplayNodes } from "@/features/workflows/useWorkflowDisplayElements";
import { useWorkflowPortNamer } from "@/features/workflows/useWorkflowPortNamer";
import { workflowRefNamer } from "@/features/workflows/workflowRefCatalog";
import { useWorkflowEditorShortcuts, useWorkflowNodeZ } from "@/features/workflows/useWorkflowEditorKeys";
import { useWorkflowGraph } from "@/features/workflows/useWorkflowGraph";
import { useWorkflowRun } from "@/features/workflows/useWorkflowRun";
import { useWorkflowSave } from "@/features/workflows/useWorkflowSave";
import { useWorkflowComments } from "./WorkflowComments";
import { workflowEditorToolbar } from "@/features/workflows/WorkflowEditorToolbar";
import { TemplateUpgradeNotice } from "@/features/workflows/TemplateUpgradeNotice";
import { WorkflowRevisionHistory } from "@/features/workflows/WorkflowRevisionHistory";
import { WorkflowRunHistory } from "@/features/workflows/WorkflowRunHistory";
import { withSingleNodeSelected } from "@/features/workflows/workflowCanvasModel";
import { WORKFLOW_CANVAS_CLASS } from "@/features/workflows/workflowCanvasSkin";
import {
  AGENT_MODES,
  AGENT_PANEL_KEY,
  DEFAULT_EDGE_OPTIONS,
  isMarkerNode,
  refreshAfterWorkflowDelete,
  WORKFLOW_CANVAS_NODE_TYPES,
} from "@/features/workflows/workflowViewShared";
import { saveJsonToDisk } from "@/lib/download";
import { formatCombo } from "@/lib/shortcuts";
import { ROW_HANDLE_CLASS, handleOffset, useResizableRow, useResizableSidebar } from "@/lib/useResizableSidebar";
import { usePersistentTab, usePersistentViewport } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";
import { useUnusableNodeReasons } from "@/features/workflows/useUnusableNodeReasons";

/**
 * 工作流的详情页:整页一块画布。图、保存、运行、画布上的编辑动作各在一个 hook 里
 * (useWorkflowGraph / useWorkflowSave / useWorkflowRun / useWorkflowCanvasEdits),
 * 顶上的工具条在 WorkflowEditorToolbar,选中节点的检查器在 NodeInspector。
 */
export function WorkflowEditor({
  workflow,
  nodeTypes,
  workspaceId,
  onBack,
  openRunId = null,
  onRunOpened,
}: {
  workflow: Workflow;
  nodeTypes: WorkflowNodeType[];
  workspaceId: string;
  /** 返回列表。**和标题同一行** —— 单独占一行会把整条工具栏挤下去(第一版就是这么做的)。 */
  onBack: () => void;
  /** 从别处点过来要看的那一次运行(浏览器悬浮卡片的标题):打开执行历史、停在那一次,然后交回 onRunOpened。 */
  openRunId?: string | null;
  onRunOpened?: () => void;
}) {
  const [markerMode, setMarkerMode] = React.useState(false);
  const [markersVisible, setMarkersVisible] = React.useState(true);
  const workflowComments = useWorkflowComments(workspaceId, workflow.id);
  const [collaborationOpen, setCollaborationOpen] = React.useState(false);
  const annotationMode = markerMode || workflowComments.active;
  const enterMarkerMode = () => { workflowComments.exit(); setMarkerMode(true); setMarkersVisible(true); };

  const [inputMode] = useCanvasInputMode();
  const t = useI18n();
  const qc = useQueryClient();
  const registry = React.useMemo(() => new Map(nodeTypes.map((item) => [item.type, item])), [nodeTypes]);
  const { options: nodeOptions } = useNodePicker(nodeTypes, t);

  const {
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
  } = useWorkflowGraph({
    workflow,
    registry,
    t,
    markerMode,
    markersVisible,
    commentsActive: workflowComments.active,
  });
  const [showHistory, setShowHistory] = React.useState(false);
  const [showRevisions, setShowRevisions] = React.useState(false);
  const [renaming, setRenaming] = React.useState(false);
  //: 顶栏的路径:工作流 / 这一个 / 钻进去的每一层(子图、循环体)。在最外层时点名字改名;钻进去了,名字和中间
  //: 每一层都点得回去(此前是画布左上角一颗「← 回上一层」,一层一层退)。
  const scopeLabel = (node: WorkflowGraph["nodes"][number]) =>
    `${node.name || registry.get(node.type)?.label || node.type} · ${t(node.type === "subgraph" ? "wfSubgraphBody" : "wfLoopBody")}`;
  usePageTrail({
    onRoot: onBack,
    segments: [
      atRoot
        ? { label: workflow.name, onRename: () => setRenaming(true), renameLabel: t("rename") }
        : { label: workflow.name, onSelect: () => enterScope([]) },
      ...scopePath.map((_, index) => {
        const node = scopeContainer(rootGraph, scopePath.slice(0, index + 1), registry);
        const last = index === scopePath.length - 1;
        return {
          label: node ? scopeLabel(node) : "…",
          onSelect: last ? undefined : () => enterScope(scopePath.slice(0, index + 1)),
        };
      }),
    ],
  });
  const [deleting, setDeleting] = React.useState(false);
  // 导出走后端信封(格式和版本的权威在后端),落成 .mosael-workflow.json —— 和列表页
  // 右键那条是同一个函数,不另写一份:两份迟早会在文件名或格式上分叉。
  const exportFile = useMutation({
    mutationFn: async () => {
      const envelope = await exportWorkflowFile(workflow.id);
      saveJsonToDisk(`${workflow.name}.mosael-workflow.json`, envelope);
    },
    onError: (error: Error) => toast.error(t("wfExportFailed"), { description: error.message }),
  });
  // 默认关闭:进工作流页是来看画布的,助手默认占掉右侧近一半、把节点挤到看不见。
  // 需要时点顶栏「AI 助手」;开关状态记住,下次进来照旧。
  const [agentOpen, setAgentOpen] = React.useState(() => localStorage.getItem(AGENT_PANEL_KEY) === "1");
  React.useEffect(() => {
    localStorage.setItem(AGENT_PANEL_KEY, agentOpen ? "1" : "0");
  }, [agentOpen]);
  // 停靠还是浮窗,是布局偏好 —— 每次回来都弹回"停靠"等于每次都要重摆一遍。
  const [agentMode, setAgentMode] = usePersistentTab<CanvasAgentMode>("wf-agent-mode", "docked", AGENT_MODES);
  /** 执行历史与助手同一套停靠/悬浮机制,但各记各的模式与几何。 */
  const [historyMode, setHistoryMode] = usePersistentTab<CanvasAgentMode>("wf-history-mode", "docked", AGENT_MODES);
  const dockedAgent = agentOpen && agentMode === "docked";
  const dockedHistory = showHistory && historyMode === "docked";
  const rightPanels = (dockedAgent ? 1 : 0) + (dockedHistory ? 1 : 0);
  const rightPanel = useResizableSidebar("workflow-right", { min: 320, max: 640, fallback: 400 });
  const rightOcclusion = rightPanels > 0 ? canvasRightDockOcclusion(rightPanel.width) : 0;
  const [edgeShape, setEdgeShape] = useEdgeShape("wf-edge-shape");
  //: 右下角的全览。默认开着 —— 大图时它最有用,而"图大不大"只有用户自己知道。
  const [minimapMode, setShowMinimap] = usePersistentTab<"on" | "off">("wf-minimap", "on", ["on", "off"] as const);
  const showMinimap = minimapMode === "on";
  //: 查找节点的命中集 —— 画在节点外壳上(见 CanvasNodeSearch)。
  const [searchHit, setSearchHit] = React.useState<CanvasSearchHighlight | null>(null);
  // While a node is being dragged we pause auto-save: a mid-drag PATCH→refetch would rebuild the
  // graph and interrupt React Flow's drag. The save fires once, right after the drag settles.
  const [dragging, setDragging] = React.useState(false);
  const rfRef = React.useRef<ReactFlowInstance | null>(null);
  const canvasSurfaceRef = React.useRef<HTMLDivElement | null>(null);
  /** 整块编辑器(工具条 + 画布 + 检查器)。删除键只认从这里面发出的按键,见 isCanvasKeyTarget。 */
  const editorRef = React.useRef<HTMLDivElement | null>(null);
  const agentPanelRef = React.useRef<HTMLDivElement | null>(null);
  const historyPanelRef = React.useRef<HTMLDivElement | null>(null);
  // 悬浮时 wrapper 是 display:contents,量它自己拿到的是空矩形 —— 要量的是里面那块面板。
  const getCanvasInsets = React.useCallback(
    () =>
      canvasInsets(canvasSurfaceRef.current, rightOcclusion, [
        agentOpen && agentMode === "floating" ? agentPanelRef.current?.firstElementChild : null,
        showHistory && historyMode === "floating" ? historyPanelRef.current?.firstElementChild : null,
      ]),
    [rightOcclusion, agentOpen, agentMode, showHistory, historyMode],
  );
  // 画布姿态(是否已 fitView、视口动过几次、正不正在平移)。三条各自的来历见 useCanvasPosture
  // —— 它们是 React Flow 的机制,不是工作流的概念,所以不和图 / 弹窗 / 搜索那些 state 混在一起。
  const canvas = useCanvasPosture();
  // 每张工作流、每一层各记各的位置 —— 换一张图、钻进一层,不该继承上一处停在哪儿。
  const viewport = usePersistentViewport(atRoot ? `workflow:${workflow.id}` : `workflow:${workflow.id}:${scopePath.join(":")}`);
  /** 从别的层点了就绪清单里的某个节点:换到它那一层,等**那一层**的画布挂好再聚焦它。记着是哪一层 ——
   *  上一层的画布若还没走完自己的定位(onInit 在下一帧),它不能把这一笔领走。 */
  const pendingFocusRef = React.useRef<{ scope: string; nodeId: string | null } | null>(null);
  /** 哪一层的画布已经定位好了。 */
  const [placedScope, setPlacedScope] = React.useState<string | null>(null);

  /** 让画布只选中这一个(null = 全不选)。检查器跟着选中态走,见 selectedNodeId。 */
  const selectInspectorNode = React.useCallback((nodeId: string | null) => {
    setNodes((current) => withSingleNodeSelected(current, nodeId));
  }, []);
  /**
   * 把视口居中到某坐标上。用坐标而非 getNode:新加节点此刻还没同步进 React Flow 内部 store,
   * getNode 会取空;而 setCenter 只改视口变换,不依赖节点已登记。
   *
   * 检查器在节点下方，聚焦时把「节点 + 检查器」作为整体居中；如果只把节点放正中，
   * 560px 高的面板必然掉出画布底边。面板本身不随画布缩放，所以屏幕像素要除以 zoom
   * 再换回流程坐标。
   */
  const focusPosition = React.useCallback((x: number, y: number, duration = 350, size = { width: 210, height: 72 }) => {
    const instance = rfRef.current;
    const surface = canvasSurfaceRef.current;
    if (!instance || !surface) return;
    const zoom = Math.max(instance.getZoom(), 0.6);
    const insets = getCanvasInsets();
    const visible = visibleCanvasSize(surface.clientWidth, surface.clientHeight, insets);
    const inspectorOffset = Math.min(220, visible.height * 0.2) / zoom;
    void centerCanvasViewport(instance, surface,
      { x: x + size.width / 2, y: y + size.height / 2 + inspectorOffset },
      insets, { zoom, duration });
  }, [getCanvasInsets]);

  /** 选中并聚焦某节点(节点搜索用;从当前 graph 取坐标)。 */
  const focusNode = React.useCallback(
    (nodeId: string) => {
      const target = graph.nodes.find((node) => node.id === nodeId);
      if (!target) return;
      selectInspectorNode(nodeId);
      const measured = rfRef.current?.getNode(nodeId);
      focusPosition(target.position?.x ?? 0, target.position?.y ?? 0, 350, {
        width: measured?.measured?.width ?? measured?.width ?? 210,
        height: measured?.measured?.height ?? measured?.height ?? 72,
      });
    },
    [graph.nodes, focusPosition, selectInspectorNode],
  );
  //: 查找节点搜整张图(每个循环体 / 子图里的也算,见 nodeSearch),搜的是:改过的名字、类型的显示名、
  //: 类型的原始值(按 `llm` 也能找到「大模型」)、节点 id(报错和就绪清单说的就是它)。
  const searchEntries = React.useMemo(
    () => nodeSearchTargets(rootGraph, registry),
    [rootGraph, registry],
  );
  /** 跳到搜到的那个节点:在别的层就先换过去,等那一层的画布挂好再聚焦(同就绪清单那条)。 */
  const jumpToSearchEntry = React.useCallback(
    (entryId: string) => {
      const target = searchEntries.find((one) => one.id === entryId);
      if (!target) return;
      if (scopeId(target.path) === scopeKey) {
        focusNode(target.nodeId);
        return;
      }
      pendingFocusRef.current = { scope: scopeId(target.path), nodeId: target.nodeId };
      enterScope(target.path);
    },
    [searchEntries, scopeKey, focusNode, enterScope],
  );
  const layerSearchHit = React.useMemo(
    () => highlightAtLayer(searchHit, searchEntries, scopePath),
    [searchHit, searchEntries, scopePath],
  );

  const {
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
  } = useWorkflowCanvasEdits({
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
  });

  const { save, pendingSaveRef, adoptServerWorkflow } = useWorkflowSave({
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
  });
  const openRevisions = React.useCallback(async () => {
    // 历史必须以已落库的当前图为基准。若自动保存还在等待，先复用同一条保存 Interface，
    // 成功后再开；否则用户可能恢复旧版后又被 700ms 前排队的本地保存覆盖。
    if (pendingSaveRef.current) {
      try {
        await save.mutateAsync();
      } catch {
        return;
      }
    }
    setShowRevisions(true);
  }, [save]);
  const rename = useMutation({
    mutationFn: (name: string) => updateWorkflow(workflow.id, { name }),
    onSuccess: () => {
      setRenaming(false);
      void qc.invalidateQueries({ queryKey: ["workflows", workspaceId] });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteWorkflow(workflow.id),
    onSuccess: () => refreshAfterWorkflowDelete(qc, workspaceId),
  });
  const {
    runJobId,
    viewedRun,
    viewRun,
    runByNode,
    running,
    stop,
    run,
    analysis,
    layerIssues,
    launching,
    startRun,
    checklistCount,
    checklistLabel,
    checklistOpen,
    setChecklistOpen,
  } = useWorkflowRun({ workflow, qc, t, rootGraph, registry, scopePath, save, pendingSaveRef });
  React.useEffect(() => {
    if (!openRunId) return;
    viewRun(openRunId);
    setShowHistory(true);
    onRunOpened?.();
    // 只认「又有一次要看」这一件事;viewRun / onRunOpened 换引用不该重放
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openRunId]);
  //: 就绪清单里认不出的插件节点为什么用不了(后端的真实原因;画布角标、检查器问的是同一份缓存)。
  const unusableReasons = useUnusableNodeReasons(
    React.useMemo(
      () => analysis.issues.filter((issue) => issue.code === "unknown-type").map((issue) => issue.nodeType),
      [analysis.issues],
    ),
  );
  const selectedNode = graph.nodes.find((node) => node.id === selectedNodeId) ?? null;

  // 角标信息塞进节点 data(不动 nodes 状态本身,避免打断拖拽)。
  const agentPanel = (
    <div ref={agentPanelRef} className="contents"><CanvasAgentChat
      contextLine={t("wfAgentContext").replace("{id}", workflow.id).replace("{name}", workflow.name)}
      emptyHint={t("wfAgentEmpty")}
      placeholder={t("wfAgentPlaceholder")}
      rectKey="mosael.wf.agent.rect.v2"
      workspaceId={workflow.workspace_id}
      mode={agentMode}
      onModeChange={setAgentMode}
      onClose={() => setAgentOpen(false)}
    /></div>
  );
  const historyPanel = (
    <div ref={historyPanelRef} className="contents"><WorkflowRunHistory
      workflowId={workflow.id}
      registry={registry}
      viewedRunId={viewedRun}
      onViewRun={viewRun}
      // 历史面板据此判断某一步的输出是不是素材(节点注册表里声明为 asset),
      // 是就渲染成缩略图/播放器而不是一串裸 id。
      nodeTypeById={Object.fromEntries(rootGraph.nodes.map((n) => [n.id, n.type]))}
      mode={historyMode}
      onModeChange={setHistoryMode}
      onClose={() => setShowHistory(false)}
    /></div>
  );
  const fitCanvas = React.useCallback(
    (instance: ReactFlowInstance, duration = 250) => {
      if (!canvasSurfaceRef.current) return;
      void fitCanvasViewport(
        instance,
        canvasSurfaceRef.current,
        getCanvasInsets(),
        { padding: 0.3, duration, maxZoom: 1 },
      );
    },
    [getCanvasInsets],
  );
  // 助手与执行历史上下分。上界给得宽 —— 只想看助手时把它拉满是合理的用法。
  const agentRow = useResizableRow("workflow-agent", { min: 160, max: 900, fallback: 420 });

  const displayEdges = useWorkflowDisplayEdges(edges, runByNode, edgeShape);
  //: `{{…}}` 引用画成淡点线(只管先后,不让被引用的节点跑);被引用的不会跑时是错误色。不在图里,只叠在显示上。
  const referenceHintEdges = useReferenceHintEdges(graph, registry, { entryIsRoot: !atRoot, shape: edgeShape, t });

  useWorkflowEditorShortcuts({ save, startRun });

  //: Backspace / Delete 只删冲着画布来的那一下(检查器里的按钮、Portal 出去的下拉不算)——
  //: 和画板同一个钩子,见 components/app/useCanvasDeleteKey。
  useCanvasDeleteKey(editorRef, rfRef);

  const nodeZ = useWorkflowNodeZ(nodes);

  //: 就绪检查的提示(画布角标、就绪清单)里提到的引用,按它所在那一层说成「节点标题 · 输出」。
  const refName = React.useMemo(() => workflowRefNamer(rootGraph, registry), [rootGraph, registry]);
  //: 卡片上的接点叫什么:和检查器那一格同一个名字,按界面语言(见 portNames)。
  const portNamer = useWorkflowPortNamer(rootGraph, registry);
  const displayNodes = useWorkflowDisplayNodes({
    nodes,
    graph,
    registry,
    refName,
    portNamer,
    t,
    layerIssues,
    runByNode,
    nodeZ,
    markers,
    patchMarker,
    deleteMarker,
    markerMode,
    markersVisible,
    annotationMode,
    searchHit: layerSearchHit,
    atRoot,
  });

  return (
    // 间距和别的页面一样是 8px:外框已经有 p-2,这里给 gap-2 就够,工具条自己不再另加
    // 上下内边距 —— 此前是 pb-2 pt-0.5(下 8 上 2),上下差四倍,顶栏看着往上贴。
    // **工具条浮在画布上,不再占一整行。** 画布因此从上到下是完整的一块 —— 此前顶上那条
    // 实心横带把可视区切掉一截,而工作流恰恰是越大越好看的东西。
    //
    // 没有照搬参考产品的左侧竖直悬浮栏:我们左边**已经有一条全局导航栏**,再加一条竖栏就是
    // 两条并排的竖条,用户得先分辨"哪条是应用的、哪条是这一页的"。所以横向成组、浮在顶部,
    // 保持"这一页的操作"和"整个应用的导航"在方向上就分得开。
    <div ref={editorRef} className="relative grid min-h-0">
      <div className="pointer-events-none absolute inset-x-2 top-2 z-20 flex items-start justify-end gap-2 [&>*]:pointer-events-auto">
        {/* 「这是哪一个工作流、钻到了第几层」写在顶栏的路径里(工作流 / 批量配音 / 循环体,见
            components/layout/pageTrail),画布上只浮着操作这一组。保存状态没有单独的指示:失败弹 toast,运行键的 title 说「保存中」/「上次保存失败」。 */}
        {/* 正停在一次较早的运行上:画布、检查器、历史三处都在说那一次,得有一个一眼看得到的出口回到最新。
            挂在画布上而不是历史面板里 —— 面板关了,画布照样停在那一次。 */}
        {/* 从旧版官方模板建的图:说一声,点一下按新版重建(旧图保留)。见 TemplateUpgradeNotice。 */}
        <TemplateUpgradeNotice workflowId={workflow.id} meta={rootGraph?.meta} />
        {viewedRun !== runJobId && (
          <div
            role="status"
            data-wf-viewing-past-run=""
            className={cn(CANVAS_GLASS_SURFACE_CLASS, "flex h-[42px] shrink-0 items-center gap-2 rounded-lg pl-3 pr-1 text-ui-xs text-muted-foreground")}
          >
            <History size={13} className="shrink-0" />
            <span className="whitespace-nowrap">{t("wfViewingPastRun")}</span>
            <Button size="sm" variant="secondary" onClick={() => viewRun(null)}>
              {t("wfBackToLatestRun")}
            </Button>
          </div>
        )}
        {workflowEditorToolbar({
          t,
          workflow,
          registry,
          unusableReasons,
          refName,
          agentOpen,
          setAgentOpen,
          setAgentMode,
          analysis,
          checklistCount,
          checklistLabel,
          checklistOpen,
          setChecklistOpen,
          scopeKey,
          enterScope,
          focusNode,
          pendingFocusRef,
          showHistory,
          setShowHistory,
          running,
          stop,
          run,
          launching,
          startRun,
          save,
          dirty,
          openRevisions,
          exportFile,
          setRenaming,
          setDeleting,
          nodeOptions,
          canAddStart,
          addNode,
          canUndo,
          canRedo,
          undo,
          redo,
          atRoot,
          workflowComments,
          setCollaborationOpen,
          markerMode,
          setMarkerMode,
          enterMarkerMode,
          markersVisible,
          setMarkersVisible,
          markers,
          jumpToMarker,
          searchEntries,
          jumpToSearchEntry,
          selectedSearchEntry: selectedNodeId ? nodeSearchEntryId(scopePath, selectedNodeId) : null,
          setSearchHit,
          edgeShape,
          setEdgeShape,
          showMinimap,
          setShowMinimap,
          rfRef,
          fitCanvas,
        })}
      </div>

      <div className={cn(
        CANVAS_EDGE_CLASS,
        WORKFLOW_CANVAS_CLASS,
        "relative grid min-h-0 grid-cols-[minmax(0,1fr)] gap-2",
      )}
        // 画布**始终占满**:助手和执行历史改成浮在上面,不再从画布身上切走一列。
        // 工具条已经浮起来了,右边再留一条实心栏,画布就被两面夹住 —— 而这一页的主角是画布。
      >
        {/* 画布和右栏之间的拖柄。右栏是从右往左量的,所以给 right 而不是 left。 */}
        {/* 拖柄:面板浮起来之后它不再是"两栏之间的界",而是浮窗自己的左边缘 —— 所以贴着
            浮窗左侧,并跟着浮窗一起压在画布上(z-10),否则会被画布吃掉指针事件。 */}
        {rightPanels > 0 && (
          <RightDockResizeHandle panel={rightPanel} toolbarTop={8} className="z-10" />
        )}
        {/* 从访达直接把视频/图片拖进画布:先进素材库,再在**落点**放一个「素材」节点。
            省掉「先去素材页上传 → 回来找那个 id」那一圈。 */}
        <div
          ref={canvasSurfaceRef}
          //: 底色和创意画板那张画布同一个(bg-background)—— 两者都是「摊开东西的地方」,
          //: 而 bg-panel 是「一块面板」。用两种底色的话,在两页之间切换会觉得走进了另一个应用。
          className="relative min-h-0 overflow-hidden bg-background"
          {...canvasDrop.handlers}
          onDrop={(event) => {
            // 落点要在这一刻算 —— 只有事件里才有鼠标位置。存进 ref 给上面那个回调用。
            const instance = rfRef.current;
            pendingDropAt.current = instance
              ? instance.screenToFlowPosition({ x: event.clientX, y: event.clientY })
              : null;
            canvasDrop.handlers.onDrop(event);
          }}
        >
          {/* inset-0 一点不留:提示盖住整块画布,虚线只收在中间那块文字上。 */}
          {(canvasDrop.active || dropUpload.isPending) && (
            // **要盖过画布上的一切**,包括节点检查器那张浮层(z-30)和子流程面板(同样 z-30)。
            // z-20 的时候,选中某个节点再拖文件进来,检查器就压在提示上面 —— 用户看到的是
            // 半块被切掉的虚线框,不知道松手到底会发生什么。拖拽反馈是**全局态**,不该和
            // 画布里某个局部面板比高矮。
            <div className="pointer-events-none absolute inset-0 z-40 grid place-items-center bg-[color-mix(in_oklab,var(--primary)_10%,var(--background))]">
              <span className="grid justify-items-center gap-2 rounded-lg border-2 border-dashed border-primary px-6 py-4 text-ui-md font-semibold text-primary">
                {dropUpload.isPending ? (
                  <>
                    <Loader2 size={20} className="animate-mosael-spin" />
                    {t("mediaDropUploading")}
                  </>
                ) : (
                  <>
                    <FileUp size={20} />
                    {t("wfDropHint")}
                  </>
                )}
              </span>
            </div>
          )}
          <MarkerEditorProvider enabled={markerMode && markersVisible}>
          <ReactFlow
            // 每一层一个 React Flow 实例:换层时重挂,视口按那一层记的位置恢复(见 onInit)。
            key={scopeKey}
            // 定位好之前藏着 —— 按层算:换一层时新挂的画布也有一帧停在默认视口上。
            className={cn((!canvas.ready || placedScope !== scopeKey) && "opacity-0")}
            nodes={displayNodes}
            nodesConnectable={!annotationMode}
            elementsSelectable={!workflowComments.active}
            //: 提示线排在前面:后画的真连线压在它上面。它们自己就不可选(见 referenceHints),不跟着标注模式切。
            edges={[...referenceHintEdges, ...displayEdges.map(edge => ({ ...edge, selectable: !annotationMode }))]}
            nodeTypes={WORKFLOW_CANVAS_NODE_TYPES}
            edgeTypes={WORKFLOW_CANVAS_EDGE_TYPES}
            minZoom={0.1}
            onInit={(instance) => {
              const flow = instance as unknown as ReactFlowInstance;
              rfRef.current = flow;
              // 只在挂载时定位一次(切换工作流会因 key 重挂而重跑)。用命令式而非声明式
              // fitView 属性:后者会在每次新增未测量节点时重新 fit,把手动聚焦覆盖掉。
              // 定位完成前画布不可见:首帧按默认视口渲染会让所有节点在错位处闪一下。
              //
              // **上次停在哪儿就回哪儿**,只有第一次进来才 fitView。此前每次刷新/重进都 fit,
              // 把所有节点框回视野 —— 图一大,用户每次回来都得重新找到刚才在看的那一块,
              // 而他离开时的位置本来就是最有价值的信息。
              requestAnimationFrame(() => {
                if (viewport.saved) flow.setViewport(viewport.saved);
                else if (nodes.length > 4) {
                  // 兜底那一项要排除标记 —— 它排在数组最前,于是"第一次进来"会把视口
                  // 停在一枚旗子上,而不是图的开头。
                  const real = nodes.filter((node) => !isMarkerNode(node));
                  const first = real.find(node => node.data.nodeType === "start") ?? real[0];
                  // 早退会跳过下面那句 onInit(画布会一直停在"还没定位好"的不可见态)。
                  if (first) flow.setCenter(first.position.x + 450, first.position.y + 140, { zoom: 0.8, duration: 0 });
                } else fitCanvas(flow, 0);
                canvas.handlers.onInit();
                setPlacedScope(scopeKey);
                const pending = pendingFocusRef.current;
                if (pending?.scope === scopeKey) {
                  pendingFocusRef.current = null;
                  if (pending.nodeId) focusNode(pending.nodeId);
                }
              });
            }}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onMoveStart={canvas.handlers.onMoveStart}
            onMoveEnd={(event, next) => {
              canvas.handlers.onMoveEnd();
              viewport.remember(next);
            }}
            onNodeDragStart={() => setDragging(true)}
            onNodeDragStop={() => setDragging(false)}
            onConnect={onConnect}
            isValidConnection={isValidConnection}
            connectionRadius={36}
            connectionLineType={edgeShape as ConnectionLineType}
            onNodeClick={(event, node) => {
              if (markerMode) return;
              if (workflowComments.active) { const point = rfRef.current?.screenToFlowPosition({ x: event.clientX, y: event.clientY }); if (point) workflowComments.place({ ...point, node_id: node.id }); return; }
              blurFloatingPanels(); // 层级快捷键交还给画布
              // 按着多选键(⌘/Ctrl)或 Shift 点,是往选区里加减 —— React Flow 已经改好了选中态,
              // 这里再「只选这一个并聚焦」就是把用户刚加进来的选区当场冲掉。
              if (event.metaKey || event.ctrlKey || event.shiftKey) return;
              focusNode(node.id);
            }}
            onNodeDoubleClick={(_event, node) => {
              if (annotationMode) return;
              const g = graph.nodes.find((item) => item.id === node.id);
              if (g && bodyKey(registry, g.type)) enterScope([...scopePath, node.id]);
            }}
            onPaneClick={(event) => {
              const point = rfRef.current?.screenToFlowPosition({ x: event.clientX, y: event.clientY });
              if (markerMode && point) { addMarker(point); return; }
              if (workflowComments.active && point) { workflowComments.place(point); return; }
              blurFloatingPanels();
              selectInspectorNode(null);
            }}
            {...canvasWheelProps(inputMode)}
            zoomOnPinch
          defaultEdgeOptions={DEFAULT_EDGE_OPTIONS}
            proOptions={{ hideAttribution: false }}
            // 删除键自己接(见下面那条 effect):React Flow 听整个 document,Portal 出去的下拉里
            // 按 Backspace 也会删节点。
            deleteKeyCode={null}
          >
            {atRoot && workflowComments.layer}
            {annotationMode && <AnnotationModeHint kind={markerMode ? "marker" : "comment"} onExit={() => { setMarkerMode(false); workflowComments.exit(); }} />}
            {selectedFlowIds.length >= 2 && !annotationMode && (
              <Panel position="top-center">
                <Hint label={t("wfCollapseHint")} shortcut={formatCombo("Mod+G")} side="bottom">
                  <button
                    type="button"
                    onClick={() => handleCollapse(selectedFlowIds)}
                    // **select-none**:它出现的时机正是框选拖拽刚结束的那一刻,而那一下拖拽会把
                    // 按钮上的字一起选中 —— 于是文字顶着一层系统选区的紫色,看着像坏了。
                    className="inline-flex select-none items-center gap-1.5 rounded-full border border-field-border bg-card px-3 py-1.5 text-xs font-medium text-foreground shadow-sm hover:bg-muted"
                  >
                    <Boxes size={13} /> {t("wfCollapseToSubgraph").replace("{n}", String(selectedFlowIds.length))}
                  </button>
                </Hint>
              </Panel>
            )}
            <Background gap={20} size={1.2} />
            {/* 缩放钮/预览图不吃应用主题(xyflow 默认一律白底),把 --xy-* 变量
                映射到设计令牌,昼夜两版都跟着色板走;投影按全局规范去掉。 */}
            {showMinimap && <MiniMap
              pannable
              zoomable
              position="bottom-right"
              className="overflow-hidden rounded-md border border-border"
              bgColor="var(--panel)"
              maskColor="color-mix(in srgb, var(--background) 55%, transparent)"
              nodeColor="var(--border-strong)"
              nodeStrokeColor="transparent"
            />}
        {selectedNode && !annotationMode && (
          <NodeInspector
            inert={canvas.panning}
            step={atRoot ? (runByNode[selectedNode.id] ?? null) : null}
            runSteps={atRoot ? runByNode : undefined}
            node={selectedNode}
            meta={registry.get(selectedNode.type) ?? null}
            graph={graph}
            registry={registry}
            scopeVariables={scopeVariables}
            workspaceId={workspaceId}
            workflowId={workflow.id}
            onChange={(patch, options) => {
              // 这一下是打字(一串连发)还是离散的一步,由发出它的控件说(见 NodeInspector 的
              // typingRun)。此前这里按「patch 里有 config」猜,于是换下拉、拨开关也被当成打字,
              // 和前后 400ms 里的输入并成一条历史。
              applyGraph(
                {
                  ...graph,
                  nodes: graph.nodes.map((node) => (node.id === selectedNode.id ? { ...node, ...patch } : node)),
                },
                options,
              );
            }}
            onApplyGraph={applyGraph}
            onDelete={() => {
              applyGraph({
                ...graph,
                nodes: graph.nodes.filter((node) => node.id !== selectedNode.id),
                edges: graph.edges.filter(
                  (edge) => edge.source !== selectedNode.id && edge.target !== selectedNode.id,
                ),
              });
              selectInspectorNode(null);
            }}
            onDrillIn={
              bodyKey(registry, selectedNode.type) ? () => enterScope([...scopePath, selectedNode.id]) : undefined
            }
            onClose={() => selectInspectorNode(null)}
          />
        )}
          </ReactFlow>
          </MarkerEditorProvider>
          {scopeNode && graph.nodes.length === 0 && (
            <div className="pointer-events-none absolute left-1/2 top-14 max-w-[70%] -translate-x-1/2 rounded-lg border border-dashed border-border bg-muted px-3 py-2 text-center text-xs text-muted-foreground">
              {t(scopeNode.type === "subgraph" ? "wfSubgraphEmptyHint" : "wfLoopEmptyHint")}
            </div>
          )}
        </div>

        {/* 讨论侧栏。和画板那份是同一个组件 —— 评论对后端来说只是换了个 subject_type。 */}
        <CollaborationSheet
          open={collaborationOpen}
          onOpenChange={setCollaborationOpen}
          workspaceId={workspaceId}
          subjectType="workflow"
          subjectId={workflow.id}
          onJumpToComment={(comment) => {
            setMarkerMode(false);
            workflowComments.focus(comment.id);
            setCollaborationOpen(false);
            const instance = rfRef.current;
            const surface = canvasSurfaceRef.current;
            const { x, y } = comment.anchor ?? {};
            if (!instance || !surface || typeof x !== "number" || typeof y !== "number") return;
            requestAnimationFrame(() =>
              centerCanvasViewport(instance, surface, { x, y }, getCanvasInsets(), {
                zoom: Math.max(instance.getZoom(), 0.9),
                duration: 350,
              }),
            );
          }}
        />
        {/* 右栏:助手与执行历史共用。两个都开就上下平分 —— 运行时经常要一边看画布状态、
            一边翻某一步的输出。助手切到浮动模式时自己脱离文档流,所以只按停靠中的个数分行。 */}
        {(dockedAgent || dockedHistory) && (
          <div
            className={cn(
              // 浮窗:贴右侧,从工具条底下起、到画布底边止。z-10 —— 压过画布,让过工具条(z-20)
              // 和节点检查器(z-30):检查器是"你正在改的那个东西",它该在最上面。
              "absolute z-10 grid min-h-0 min-w-0 gap-2",
              dockedAgent && dockedHistory ? "grid-rows-[minmax(0,1fr)_minmax(0,1fr)]" : "grid-rows-[minmax(0,1fr)]",
            )}
            // 两个都开时上面那块用记住的高度,下面那块吃掉剩下的 —— 运行时想看某一步的输出
            // 就把历史那块拉大,而平分是个谁都不满意的折中。
            style={{
              width: rightPanel.width,
              ...canvasDockedPanelEdges(8),
              ...(dockedAgent && dockedHistory
                ? { gridTemplateRows: `${agentRow.height}px minmax(0,1fr)` }
                : {}),
            }}
          >
            {dockedAgent && agentPanel}
            {/* 上下之间的横拖柄。和左右那条同一套外观(HANDLE_ROW),只是转了九十度。 */}
            {dockedAgent && dockedHistory && (
              <div
                className={ROW_HANDLE_CLASS}
                style={{ top: handleOffset(agentRow.height, { gap: 8 }) }}
                onPointerDown={agentRow.startDrag}
              />
            )}
            {dockedHistory && historyPanel}
          </div>
        )}
        {/* 浮动的面板不在右栏里(fixed 定位,自己脱离文档流),单独挂 —— 挂在栏内的话,
            两个都浮动时右栏根本不渲染,面板就跟着消失了。 */}
        {showHistory && !dockedHistory && historyPanel}
        {agentOpen && !dockedAgent && agentPanel}
      </div>

      <RenameDialog
        open={renaming}
        title={t("rename")}
        initialValue={workflow.name}
        onCancel={() => setRenaming(false)}
        pending={rename.isPending}
        onSubmit={(name) => rename.mutate(name)}
      />
      <ConfirmDialog
        open={deleting}
        title={t("deleteConfirmTitle")}
        body={t("wfDeleteBody")}
        onCancel={() => setDeleting(false)}
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
      <WorkflowRevisionHistory
        workflow={workflow}
        open={showRevisions}
        onOpenChange={setShowRevisions}
        onRestored={adoptServerWorkflow}
      />
    </div>
  );
}
