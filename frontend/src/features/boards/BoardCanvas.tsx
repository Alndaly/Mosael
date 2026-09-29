import { CANVAS_WINDOW_SURFACE_CLASS } from "@/components/app/canvasPanelLayout";
import { AnnotationModeHint } from "@/features/markers/AnnotationModeHint";
import { NO_UPSTREAM, upstreamOf } from "./boardUpstream";
import { NotePickerDialog } from "@/features/notes/NotePickerDialog";
import { useCanvasInputMode, canvasWheelProps } from "@/components/app/canvasInputMode";
import React from "react";
import {
  Background,
  BackgroundVariant,
  MiniMap,
  ReactFlow,
  NodeToolbar,
  Position,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type ConnectionLineType,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from "@xyflow/react";
import { FileUp, Loader2 } from "lucide-react";

import { type CollaborationComment, type WorkspaceMember } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { fitCanvasViewport, type CanvasViewportInsets } from "@/components/app/fitCanvasViewport";
import { shapeEdges, type EdgeShape } from "@/components/app/canvasEdgeShape";
import { CANVAS_EDGE_CLASS, CANVAS_EDGE_OPTIONS } from "@/components/app/canvasEdges";
import {
  PENDING_GHOST_ID,
  PENDING_LINK_NODE_TYPES,
  PendingLinkMenu,
  ghostRect,
  pendingLinkFromRelease,
  usePendingLink,
} from "@/components/app/canvasPendingLink";
import { searchHighlightClass, type CanvasSearchHighlight } from "@/components/app/CanvasNodeSearch";

import { type BoardCanvas as Canvas, type BoardItem, type BoardProducer, type BoardProducerInfo, type BoardRunRequest, type GenerationOption } from "@/api/client";
import { usePersistentViewport } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";
import { listenKeys } from "@/lib/shortcuts";
import { canRedo, canUndo } from "@/features/boards/canvasHistory";
import { SequenceAddContext } from "@/features/boards/sequenceCursor";
import { TrimComposer } from "@/features/boards/TrimComposer";
import { canAskWriter, canOpenOnDemand, composerOnDemand, renderAbility, renderComposer } from "@/features/boards/boardComposers";
import { BOARD_NODE_TYPES, DEFAULT_SIZE, kindIcon, kindText, SPAWNABLE_KINDS } from "@/features/boards/boardNodes";
import { composerView, newSlotForm, producerOf, runningAbility, withAbility, withProducer } from "@/features/boards/boardItemState";
import { BOARD_NODE_PANEL_OFFSET } from "@/features/boards/boardLayout";
import { type PlacedAsset } from "@/features/boards/boardPlacement";
import { useCanvasDeleteKey } from "@/components/app/useCanvasDeleteKey";
import { type CommentDraft } from "@/features/collaboration/CommentComposer";
import { MarkerPin } from "@/features/markers/MarkerPin";
import { MarkerEditorProvider } from "@/features/markers/MarkerEditorProvider";
import { toMarkerNodes, type CanvasMarker } from "@/features/markers/markers";
import {
  LAYERS,
  boardItems,
  canPlaceCommentDraft,
  copySelected,
  focusBoardNode,
  toNodes,
  type BoardPickAsset,
} from "@/features/boards/boardCanvasModel";
import { ItemToolbar, TRIM_PANEL, WRITER_PANEL } from "@/features/boards/BoardItemToolbar";
import { BoardCommentLayer, useBoardCommentDraft } from "@/features/boards/BoardCommentLayer";
import { useBoardDocuments } from "@/features/boards/useBoardDocuments";
import { useBoardFileImport } from "@/features/boards/useBoardFileImport";
import { useBoardHistory } from "@/features/boards/useBoardHistory";
import { useBoardSequenceLinks } from "@/features/boards/useBoardSequenceLinks";
import { useBoardViewport } from "@/features/boards/useBoardViewport";
import { useFrameDrag } from "@/features/boards/useFrameDrag";

//: 纯函数拆到了 boardCanvasModel.ts;别处(和测试)仍从这里取。
export {
  boardItems,
  canMoveComment,
  canPlaceCommentDraft,
  copySelected,
  focusBoardNode,
  moveCommentAnchorByScreenDelta,
  searchFocusZoom,
  shouldDismissCommentOverlay,
  shouldSuppressCommentPlacement,
  toCanvas,
} from "@/features/boards/boardCanvasModel";

/** 拉线松手后那块占位的大小:选的时候不随高亮变(见 usePendingLink),取一格图片的默认大小。 */
const PENDING_GHOST_SIZE = DEFAULT_SIZE.image;

/**
 * 创意画板的画布。
 *
 * 复用 React Flow 而不是自己写一个无限画布:平移缩放、框选、连线、小地图这些都不是这个功能
 * 的创新点,而每一样自己写都要踩一遍别人踩过的坑(触控板惯性、缩放锚点、连线命中判定)。
 * 工作流那边已经证明这层能用。
 *
 * **画布状态住在 React Flow 里,画板数据住在上面。** 两者靠 `toCanvas` 单向汇出 ——
 * 双向同步会打架:拖动时 React Flow 每帧改一次位置,回写又会重建节点,拖到一半会跳。
 */

/** 只放**数据**。回调在渲染时注入(见 baseNodes)—— 存进节点里的话,它们会闭包住
 *  还没声明的 setNodes,而这个顺序绕不开:节点的初值本身就要用到它们。 */
/** 画布交出去的把手。**只此一处** —— 上层曾经自己抄了一份同样形状的类型,加一个动作
 *  (撤销)时抄的那份不会报错,只会让按钮点了没反应。 */
export interface BoardCanvasApi {
  add: (kind: BoardItem["kind"], extra?: Partial<BoardItem>) => void;
  /** 就地改某一项(填产出、写文字、标记开始生成)。**得走这条** —— 画布的节点只在挂载时
   *  从 canvas 建一次,回写上层的 canvas 状态它看不见,用户会以为「点了没反应」。
   *  值给 undefined 表示删掉那个字段。 */
  patch: (itemId: string, next: Partial<BoardItem>) => void;
  /** Replace the local projection after a server conflict. This is intentionally explicit: normal
   *  prop changes must not interrupt an in-progress drag or text edit. */
  replace: (canvas: Canvas) => void;
  fitView: () => void;
  focusComment: (comment: CollaborationComment) => void;
  /** 查找节点跳到某一项:把它摆到看得见的那块正中,放得下的话拉近到看得清。不改选中态。 */
  focusItem: (itemId: string) => void;
  /** 位置书签。清单挂在工具条上,而它读的是画布这一份(事实来源在 React Flow 的节点里)。 */
  markers: CanvasMarker[];
  addMarker: () => void;
  jumpToMarker: (marker: CanvasMarker) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}

/** 画板的节点 + 标记 + 拉线松手时的占位。**后两样都不是画板项**,所以它们进不了
 *  BOARD_NODE_TYPES 那张按 kind 索引的表。 */
const CANVAS_NODE_TYPES = { ...BOARD_NODE_TYPES, marker: MarkerPin, ...PENDING_LINK_NODE_TYPES };

export function BoardCommentModeHint({ onExit }: { onExit?: () => void }) {
  return <AnnotationModeHint kind="comment" onExit={onExit} />;
}

interface Props {
  boardId: string;
  /** 提示词面板里 `@` 引用素材时去哪个工作区找。 */
  workspaceId: string;
  canvas: Canvas;
  onChange: (canvas: Canvas) => void;
  /** 让上层开素材选择器。kind 决定它列图片还是视频 —— 选得到的就该是贴上去能看的;`media` 是三种都列。
   *  `onBoard`:这张画板上已有的素材,选择器里多一个「画板上的」筛选。 */
  onPickAsset: BoardPickAsset;
  /**
   * 在某一格上跑一个产出者(生成、写字、念出来、截一段)。上层拿得到 workspaceId 和接口,画布只
   * 提供「落在哪一格」和「表单是什么」。写字同步返回,其余摆好占位就回、产出由回执填回来。
   */
  onRun?: (request: BoardRunRequest) => Promise<unknown>;
  /** 取某一帧,存成一份新素材、落到一个新节点上 —— 原素材不动。 */
  onGrabFrame?: (input: { assetId: string; at: number; x: number; y: number }) => Promise<unknown>;
  /** 可用的生成模型 —— 提示词面板要让人选。 */
  models?: GenerationOption[];
  /** 这个人能用的产出者(后端 GET /api/boards/producers):一格的能力(操作条上那一排)、它们的面板、
   *  空槽在几个产出者之间的切换都照它。还没到是 undefined。 */
  producers?: BoardProducerInfo[];
  /** 停下某一格正在跑的任务(运行态外壳上的停止按钮)。 */
  onStop?: (itemId: string) => void;
  /** 全览开着没有。占右下角一块不小的地方,图小的时候纯属挡视线。 */
  showMinimap?: boolean;
  /** 连线的走线方式。是看图习惯(存在本地偏好里),不写进画布 —— 见 components/app/canvasEdgeShape。 */
  edgeShape?: EdgeShape;
  /** 查找节点的命中集。命中的项外面画一圈(见 CanvasNodeSearch)。 */
  searchHighlight?: CanvasSearchHighlight | null;
  /** 系统里拖进来 / 粘贴进来的文件:上层负责传进素材库,回来的每一份(图片、视频、音频)就地各放一格。 */
  onDropFiles?: (files: File[]) => Promise<PlacedAsset[]>;
  uploading?: boolean;
  /**
   * 画布上被右栏面板盖住多少 —— 每次要用时现算(面板会拖宽、会在停靠和悬浮之间切)。
   * 全览、跳标记、跳评论、放标记都照这块**看得见的**区域来,否则目标会落在面板底下。
   *
   * 参数是画布自己的 DOM:**谁盖住了画布**由页面知道,**画布多大**由画布知道,
   * 两边各说各的那一半。
   */
  getInsets?: (surface: HTMLElement) => CanvasViewportInsets;
  /** Comment mode is separate: a canvas or node click anchors a discussion instead of editing nodes. */
  commentMode?: boolean;
  markerMode?: boolean;
  markersVisible?: boolean;
  /** 跳到一枚标记之前把标记显示出来:快捷键跳、清单里跳都走 jumpToMarker,显不显示由页面管。 */
  onRevealMarkers?: () => void;
  commentsVisible?: boolean;
  comments?: CollaborationComment[];
  members?: WorkspaceMember[];
  currentUserId?: string | null;
  activeCommentId?: string | null;
  onSelectComment?: (comment: CollaborationComment | null) => void;
  onCreateComment?: (anchor: NonNullable<CollaborationComment["anchor"]>, draft: CommentDraft) => Promise<unknown>;
  onMoveComment?: (comment: CollaborationComment, anchor: NonNullable<CollaborationComment["anchor"]>) => Promise<unknown>;
  onDeleteComment?: (comment: CollaborationComment) => Promise<unknown>;
  onExitCommentMode?: () => void;
  onExitMarkerMode?: () => void;
  /** 把「加一项」交给上层 —— 顶栏那两组胶囊要摆在一起(和工作流详情页一致),
   *  而 add 依赖画布内部的 rf 实例和 setNodes,只能由画布提供。 */
  onReady?: (api: BoardCanvasApi) => void;
}

function Inner({ boardId, workspaceId, canvas, onChange, onPickAsset, onRun, onGrabFrame, models, producers, onStop, showMinimap = true, edgeShape = "default", searchHighlight = null, onDropFiles, uploading, getInsets, commentMode = false, markerMode = false, markersVisible = true, onRevealMarkers, commentsVisible = true, comments = [], members = [], currentUserId, activeCommentId, onSelectComment, onCreateComment, onMoveComment, onDeleteComment, onExitCommentMode, onExitMarkerMode, onReady }: Props) {
  const [inputMode] = useCanvasInputMode();
  const t = useI18n();
  const rf = React.useRef<ReactFlowInstance | null>(null);

  const { appendOnConnect, pickForSequence } = useBoardSequenceLinks({ rf, onPickAsset });
  const surface = React.useRef<HTMLDivElement | null>(null);
  //: Backspace / Delete 只删冲着画布来的那一下 —— 和工作流编辑器同一个钩子。实例从 Provider 取,
  //: 不等 onInit:删除键在画布挂上的那一刻就该认。
  const flow = useReactFlow();
  const flowRef = React.useRef(flow);
  flowRef.current = flow;
  useCanvasDeleteKey(surface, flowRef);
  const viewport = usePersistentViewport(`board:${boardId}`);
  const [ready, setReady] = React.useState(false);
  const { draftAnchor, setDraftAnchor, suppressPaneClick, paneHandlers } = useBoardCommentDraft({ commentMode, activeCommentId, onSelectComment });

  const [nodes, setNodes, onNodesChange] = useNodesState([...toNodes(canvas.items), ...toMarkerNodes(canvas.markers ?? [], LAYERS.marker)]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(
    canvas.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })),
  );

  React.useEffect(() => {
    if (!commentMode) setDraftAnchor(null);
    else setNodes((current) => current.map((node) => (node.selected ? { ...node, selected: false } : node)));
  }, [commentMode, setNodes]);
  React.useEffect(() => { setNodes(current => current.map(node => ({ ...node, selected: false }))); }, [markerMode, markersVisible, setNodes]);

  // 文字改动直接落进节点 data —— 走 setNodes 而不是回写上层,理由同上:
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

  /**
   * 正在改名的那一格。**两个入口一个状态**:双击节点上方的名字、操作条上的「重命名」。
   * 改好只落一次(见 BoardNodeLabel),于是整个改名是撤销历史里的一步。
   */
  const [renaming, setRenaming] = React.useState<string | null>(null);
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

  /**
   * 媒体加载出来之后,把节点高度校正成它的**自然宽高比**。
   *
   * 不校正的话:一段 16:9 的视频摆在 320×200(1.6:1)的框里,上下各留一条黑边 —— 而画板上
   * 一眼扫过去看的就是画面本身,黑边等于把每个节点都缩小了一圈。图片同理。
   *
   * **只在还没被用户拉过时才校正**:他手动调过尺寸就是他的决定,不该被媒体加载覆盖回去。
   * 判据是宽高恰好等于默认值 —— 拉过的话至少有一边不是。
   */
  // 参数显式标类型:它在 useNodesState 之前定义(初值要用它),不标的话 TS 会绕回自己身上推。
  const setAspect = React.useCallback((id: string, ratio: number): void => {
    if (!Number.isFinite(ratio) || ratio <= 0) return;
    setNodes((current: Node[]) =>
      current.map((node: Node) => {
        if (node.id !== id) return node;
        const item = (node.data as unknown as { item: BoardItem }).item;
        const preset = DEFAULT_SIZE[item.kind];
        const width = node.width ?? preset.width;
        const height = node.height ?? preset.height;
        if (width !== preset.width || height !== preset.height) return node;
        const next = Math.round(width / ratio);
        return next === height ? node : { ...node, height: next };
      }),
    );
  }, [setNodes]);

  const { documents, pickingDocument, setPickingDocument, refreshingDocument, refreshDocument } = useBoardDocuments({ nodes, setNodes, workspaceId });
  //: 选中的那个空槽/生成中的槽 —— 只有一个被选中时才挂面板,多选没有单一的作用对象。
  /** 选中的**还空着**的那一项 —— 空槽就是「等着被填」,面板挂在它下面。 */
  //: 选中的那一格底下挂哪个产出者的面板 —— 规则在 producerOf,这里只认「选中了一格」。
  const composerItem = React.useMemo(() => {
    const picked = nodes.filter((node) => node.selected && node.type !== "marker");
    if (picked.length !== 1) return null;
    return (picked[0].data as unknown as { item: BoardItem }).item;
  }, [nodes]);
  /**
   * 操作条上点开的那一块面板:「让 AI 写」(`write`)、「剪一段」(`trim`),或这一格的一项能力(产出者 id)。
   * **一次只有一块** —— 点另一项,下面那块就换成它的(TapNow 那样:上面选能力,下面的面板跟着变);再点一次
   * 同一项就收起。它是一时的界面状态(和选中一样),不进画布、不进撤销;每一项的设置存在那一格上
   * (`form.abilities`),再打开还是上次的样子。换选别的格子、按 Esc 都收起。
   *
   * 写字的面板按需挂(composerOnDemand):便签首先是自己写的字,选中它多半是要挪一挪 —— 此前一选中就弹出
   * 写作面板,挪一张便签也要先把它关掉。「剪一段」同理:选中一段片子最常见的意图是看它、拖它,不是剪它。
   */
  const [panel, setPanel] = React.useState<{ itemId: string; name: string } | null>(null);
  const togglePanel = React.useCallback(
    (itemId: string, name: string) =>
      setPanel((current) => (current?.itemId === itemId && current.name === name ? null : { itemId, name })),
    [],
  );
  React.useEffect(() => {
    if (panel && composerItem?.id !== panel.itemId) setPanel(null);
  }, [panel, composerItem]);
  React.useEffect(() => {
    if (!panel) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPanel(null);
    };
    return listenKeys(window, onKey);
  }, [panel]);
  const opened = panel && composerItem && panel.itemId === composerItem.id ? panel.name : null;
  const trimming = panel?.name === TRIM_PANEL ? panel.itemId : null;
  const slotProducer = composerItem ? producerOf(composerItem) : null;
  //: 点开的是这一格的一项能力:它的面板**换下**这一格自己的那块(场景格的渲白模、空槽的生成)。按需的面板
  //: (「让 AI 写」「导出」)的名字就是这一格自己的产出者,不是能力。
  const ability = opened && opened !== TRIM_PANEL && opened !== slotProducer ? (opened as BoardProducer) : null;
  const producer =
    slotProducer && !ability && opened !== TRIM_PANEL &&
    (!composerOnDemand(slotProducer) || (opened === slotProducer && composerItem && canOpenOnDemand(composerItem)))
      ? slotProducer
      : null;

  /**
   * 连到这个节点上的上游产出,按连线的先后。
   *
   * **这就是那条线的意思。** 连了线还要再挂一遍素材的话,线就只是根装饰;所以这里把上游
   * 已经出了产出的项收上来,交给面板照当前生成方式挂进槽位(一张图当首帧、多张当参考)。
   * 还没出产出的上游跳过 —— 它自己都还没有东西可给。
   */
  //: 截取面板照着表单上记下的那份素材截、场景格渲的是它自己的场景,都不吃上游 —— 只有吃上游的几块面板
  //: 才去算、才会被取不到的上游文档拦住。一项能力按它自己的绑定算(多输入的工具接连进这一格的上游)。
  const feeding = composerItem && ability
    ? upstreamOf(composerItem.id, boardItems(nodes), edges, documents, composerItem.form?.abilities?.[ability]?.bindings ?? {})
    : composerItem && producer && producer !== "trim" && producer !== "scene_render" && producer !== "sequence_export"
      ? upstreamOf(composerItem.id, boardItems(nodes), edges, documents)
      : NO_UPSTREAM;

  const { beginFrameDrag, dragFrame, endFrameDrag } = useFrameDrag({ nodes, setNodes });

  // ── 标记(位置书签)与视口:见 useBoardViewport ──────────────────────────────
  const { markers, patchMarker, deleteMarker, insetsOf, centerOn, jumpToMarker, focusItem, addMarker } = useBoardViewport({
    nodes,
    setNodes,
    rf,
    surface,
    getInsets,
    onRevealMarkers,
    commentMode,
  });

  /**
   * 删掉选中的这几项,**连同挂在它们上面的线**。
   *
   * 只删节点的话会留下一根两端悬空的线:画面上它跟着消失(React Flow 不画找不到端点的线),
   * 但它还在 edges 里 —— 于是下一次自动保存被后端整个拒掉(「连线两端必须都是画板上的项」),
   * 而用户只看到「画板没能保存」,和刚才删掉的那个节点对不上号。
   *
   * 键盘删除(Delete/Backspace)走的是 React Flow 自己的 deleteElements,它一直是连线一起删的
   * —— 所以这个毛病只在工具条那颗垃圾桶上,也因此更难被发现。
   */
  const removeSelected = React.useCallback(() => {
    // 两个 setter 分开调,不在 setNodes 的更新函数里顺手改 edges —— 那个函数在 StrictMode 下
    // 会被调用两次,把副作用放进去就是跑两遍。
    const gone = new Set(nodes.filter((node) => node.selected).map((node) => node.id));
    if (gone.size === 0) return;
    setNodes((current) => current.filter((node) => !gone.has(node.id)));
    setEdges((current) => current.filter((edge) => !gone.has(edge.source) && !gone.has(edge.target)));
  }, [nodes, setNodes, setEdges]);

  /** 复制选中的这几项。节点和线一起换:两个 setter 分开调,理由同 removeSelected。 */
  const copySelection = React.useCallback(() => {
    const copied = copySelected(nodes, edges);
    setNodes(copied.nodes);
    setEdges(copied.edges);
  }, [nodes, edges, setNodes, setEdges]);

  /** 一格上在跑(或上一轮跑)的那项能力叫什么:运行态那一条上写它。清单没到、查不到时不写。 */
  const abilityLabel = (item: BoardItem): string | undefined => {
    const running = runningAbility(item);
    return running ? producers?.find((one) => one.id === running)?.label : undefined;
  };

  //: 渲染用的节点 = 数据 + 这一轮的回调。**每轮重新贴** —— 回调闭包着最新的 setNodes,
  //: 而把它们存进节点数据会让节点的初值反过来依赖 setNodes,那个循环绕不开。
  const baseNodes: Node[] = nodes.map((node) =>
    node.type === "marker"
      ? { ...node, hidden: !markersVisible, focusable: markerMode, draggable: markerMode, selectable: markerMode, selected: markerMode && node.selected,
          style: { ...node.style, pointerEvents: markerMode ? "auto" : "none" },
          data: { ...node.data, markers, editable: markerMode, onChange: patchMarker, onDelete: deleteMarker } }
      : {
          ...node,
          className: searchHighlightClass(searchHighlight, node.id),
          draggable: !commentMode && !markerMode, selectable: !commentMode && !markerMode,
          data: { ...node.data, onText: setText, onAspect: setAspect, renaming: renaming === node.id, onRenaming: setRenaming, onRename: setTitle, commentMode: commentMode || markerMode, workspaceId, document: documents.get(node.id), onPickDocument: setPickingDocument, onRefreshDocument: refreshDocument, refreshingDocument: refreshingDocument === node.id,
            //: 停止属于运行态的外壳:每一种在跑的格子都有(生成、念、写、截、能力)。
            onStop,
            abilityLabel: abilityLabel((node.data as unknown as { item: BoardItem }).item) },
        },
  );
  //: 箭头、命中宽度、层次都是**画出来的那一份**才有的东西,不进画布数据(toCanvas 只存 id 和两头)。
  const baseEdges: Edge[] = shapeEdges(edges, edgeShape).map((edge) => ({
    ...edge,
    ...CANVAS_EDGE_OPTIONS,
    zIndex: LAYERS.edge,
    selectable: !commentMode && !markerMode,
  }));

  const { history, replace, stepBack, stepForward } = useBoardHistory({ nodes, edges, setNodes, setEdges, onChange });

  /**
   * 把选中的这几项圈成一组:算出它们的外接矩形,四周留一点余量,摆一个分组框。
   *
   * **框放在最底下** —— React Flow 按数组顺序画,放在后面会盖住被圈的那些项。
   */
  const groupSelection = React.useCallback(() => {
    setNodes((current) => {
      // 分组框圈的是画板项。把一枚旗子算进外接矩形,框就会为了包住它而多出一块空白。
      const picked = current.filter((node) => node.selected && node.type !== "marker");
      if (picked.length < 2) return current;
      const pad = 32;
      const left = Math.min(...picked.map((one) => one.position.x)) - pad;
      const top = Math.min(...picked.map((one) => one.position.y)) - pad - 12;
      const right = Math.max(...picked.map((one) => one.position.x + (one.width ?? 220))) + pad;
      const bottom = Math.max(...picked.map((one) => one.position.y + (one.height ?? 140))) + pad;
      const item: BoardItem = {
        id: `frame-${Date.now().toString(36)}`,
        kind: "frame",
        x: Math.round(left),
        y: Math.round(top),
        width: Math.round(right - left),
        height: Math.round(bottom - top),
      };
      return [...toNodes([item]), ...current.map((node) => ({ ...node, selected: false }))];
    });
  }, [setNodes]);

  //: ⌘/Ctrl+Z 撤销,⌘⇧Z / Ctrl+Y 重做。输入框里不劫持 —— 在便签里打字时按撤销,
  //: 用户想撤的是自己刚打的字,不是整张画布。
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey)) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      const key = event.key.toLowerCase();
      //: ⌘G 分组 —— 框选之后最常接的一步,而它此前只能靠手动加框再往里拖。
      if (key === "g") {
        event.preventDefault();
        groupSelection();
        return;
      }
      if (key === "z" && !event.shiftKey) {
        event.preventDefault();
        stepBack();
      } else if ((key === "z" && event.shiftKey) || key === "y") {
        event.preventDefault();
        stepForward();
      }
    };
    return listenKeys(window, onKey);
  }, [stepBack, stepForward, groupSelection]);

  const add = React.useCallback(
    (kind: BoardItem["kind"], extra: Partial<BoardItem> = {}) => {
      const instance = rf.current;
      // 放在**视野中心**,不是原点:画板可以拖得很远,放原点等于放到看不见的地方。
      const center = instance
        ? instance.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 })
        : { x: 0, y: 0 };
      const size = DEFAULT_SIZE[kind];
      const item: BoardItem = {
        id: `${kind}-${Date.now().toString(36)}`,
        kind,
        x: Math.round(center.x - size.width / 2),
        y: Math.round(center.y - size.height / 2),
        ...size,
        ...(kind === "note" ? { color: "yellow" } : {}),
        //: 还没有产出的一格写明它的产出者 —— 面板照它挂(见 boardItemState.producerOf)。
        ...newSlotForm(kind, extra),
        ...extra,
      };
      // **加完就选中它**:放一个空槽的下一步一定是写提示词,而面板只在选中时才挂。
      // 不选中的话用户要再点一次才知道这儿能写字。
      setNodes((current) => [
        ...current.map((node) => ({ ...node, selected: false })),
        ...toNodes([item]).map((node) => ({ ...node, selected: true })),
      ]);
      //: 把建好的那一项交回去 —— 从连线末端长出节点时,调用方还要拿它的 id 接上那条线。
      return item;
    },
    [setNodes, setText, setAspect],
  );

  /**
   * 从节点拉出一条线、松手在空白处时弹的那个菜单。
   *
   * **拉了线就说明用户已经想好了「从这儿接下去」**,这时再让他去右上角找按钮加节点、
   * 拖回来、连上,是把一个动作拆成了三个。菜单里选一种,节点就落在松手的地方并且线已经连好。
   */
  //: 此刻画布上挂着一块面板(产出者的、一项能力的,或剪一段的)—— 缩略图要让开,见 MiniMap。
  const composerShown = Boolean(trimming) || Boolean(!feeding.blocked && composerItem && (producer || ability) && onRun);

  //: 哪一张便签正在写。写字是同步的几秒,期间按钮转圈 —— 不给反馈的话用户会再点一次。
  const [writing, setWriting] = React.useState<string | null>(null);

  /**
   * 从某一项长出下一项,并连上。
   *
   * 「从这张便签生成图片」「从这张图生成视频」走的都是它:**放一个空节点、连上线,而不是
   * 直接开跑**。空节点一选中,它的表单就打开了,提示词也已经由上游那张便签填好 —— 用户
   * 还能改模型、改比例、再挂张参考图。点一下就把任务发出去的话,这些他一个都来不及说。
   */
  const spawnLinked = React.useCallback(
    (kind: (typeof SPAWNABLE_KINDS)[number], from: string, at: { x: number; y: number }, fromIsSource = true) => {
      //: 摆放规则和拉线松手时的占位是同一个函数 —— 占位在哪,节点就落在哪,选完不跳。
      const { x, y } = ghostRect(at, DEFAULT_SIZE[kind], fromIsSource);
      const item = add(kind, { x, y });
      //: 「生成文案」长出来的便签就是要 AI 写的:写作面板直接打开(整理 · 便签放下的那种等人自己写)。
      if (canAskWriter(item)) setPanel({ itemId: item.id, name: WRITER_PANEL });
      //: 线的方向照着用户拉的那一头:从 source 拉出来的,新节点是终点;反之是起点。
      setEdges((current) =>
        addEdge(
          fromIsSource
            ? { source: from, target: item.id, sourceHandle: null, targetHandle: null }
            : { source: item.id, target: from, sourceHandle: null, targetHandle: null },
          current,
        ),
      );
    },
    [add, setEdges],
  );

  /**
   * 从节点拉出一条线、松手在空白处:摆一个占位、连一根待定的线、旁边挂单子
   * (见 components/app/canvasPendingLink)。选中一种就在占位那儿建真节点、连真线。
   *
   * 单子上**只有格子**:把内容变成新内容的工具是格子自己的能力(选中它,在操作条上点),不是另一格 ——
   * 拉一根线出来只为了长出一格新的内容。
   */
  const linkChoices = SPAWNABLE_KINDS as readonly string[] as string[];
  const describeChoice = React.useCallback(
    (choice: string) => {
      const kind = choice as (typeof SPAWNABLE_KINDS)[number];
      return { icon: kindIcon(kind), ...kindText(t, kind) };
    },
    [t],
  );
  const pending = usePendingLink({
    kinds: linkChoices,
    ghostSize: PENDING_GHOST_SIZE,
    describe: describeChoice,
    onChoose: (choice, link) =>
      spawnLinked(choice as (typeof SPAWNABLE_KINDS)[number], link.nodeId, link.at, link.fromSource),
  });
  const pendingLink = pending.link;
  const cancelPending = pending.cancel;
  //: 起手那一格没了(撤销、服务端那份换进来、别处删掉),待定的线就没有一头可接 —— 一并取消。
  React.useEffect(() => {
    if (pendingLink && !nodes.some((node) => node.id === pendingLink.nodeId)) cancelPending();
  }, [pendingLink, nodes, cancelPending]);
  //: 改名改到一半那一格没了(撤销、服务端那份换进来):收掉 —— 留着的话它回来时自己又打开了输入框。
  React.useEffect(() => {
    if (renaming && !nodes.some((node) => node.id === renaming)) setRenaming(null);
  }, [renaming, nodes]);
  //: 占位和待定的线**只进画出来的这一份** —— 不进 nodes/edges,于是不会被存、不进撤销历史。
  const display = pending.decorate(baseNodes, baseEdges, edgeShape, LAYERS.pending);

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

  const annotating = commentMode || markerMode;
  const { drop, dropAt } = useBoardFileImport({ onDropFiles, setNodes, annotating, add, rf, surface });

  React.useEffect(() => {
    onReady?.({
      add,
      patch,
      replace,
      fitView: () => {
        if (rf.current && surface.current) {
          void fitCanvasViewport(rf.current, surface.current, insetsOf(surface.current));
        }
      },
      focusItem,
      focusComment: (comment) => {
        const x = comment.anchor?.x;
        const y = comment.anchor?.y;
        if (typeof x === "number" && typeof y === "number") centerOn({ x, y });
      },
      markers,
      addMarker,
      jumpToMarker,
      undo: stepBack,
      redo: stepForward,
      canUndo: canUndo(history),
      canRedo: canRedo(history),
    });
  }, [add, patch, replace, onReady, insetsOf, centerOn, focusItem, stepBack, stepForward, history, markers, addMarker, jumpToMarker]);

  return (
    // 详情页本身就是画布边界:四边满铺,不再套第二层卡片边框或圆角。
    <div
      ref={surface}
      className={cn("relative h-full w-full overflow-hidden bg-background", CANVAS_EDGE_CLASS)}
      {...drop.handlers}
      // 坐标换算要在 drop 那一刻做 —— 这里把鼠标位置存下来给上面的回调用。
      onDragOver={(event) => {
        drop.handlers.onDragOver(event);
        const instance = rf.current;
        if (instance) dropAt.current = instance.screenToFlowPosition({ x: event.clientX, y: event.clientY });
      }}
      {...paneHandlers}
    >
      <MarkerEditorProvider enabled={markerMode && markersVisible}>
      <SequenceAddContext.Provider value={pickForSequence}>
      <ReactFlow
        nodes={display.nodes}
        edges={display.edges}
        connectionLineType={edgeShape as ConnectionLineType}
        nodeTypes={CANVAS_NODE_TYPES}
        minZoom={0.1}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(event, node) => {
          if (markerMode || node.id === PENDING_GHOST_ID) return;
          if (commentMode) {
            if (!canPlaceCommentDraft(commentMode, Boolean(draftAnchor), suppressPaneClick.current)) return;
            const instance = rf.current;
            if (!instance) return;
            const point = instance.screenToFlowPosition({ x: event.clientX, y: event.clientY });
            setDraftAnchor({ kind: "canvas", x: point.x, y: point.y, node_id: node.id });
            return;
          }
          // 修饰键交给 React Flow 保留框选/多选语义；普通点击则显式聚焦，不能依赖它的内部
          // selection change 与受控 nodes 回写谁先落地，否则偶发要第二次点击才会稳定选中。
          if (event.shiftKey || event.metaKey || event.ctrlKey) return;
          setNodes((current) => focusBoardNode(current, node.id));
        }}
        onPaneClick={(event) => {
          if (markerMode && rf.current) { addMarker(rf.current.screenToFlowPosition({ x: event.clientX, y: event.clientY })); return; }
          if (!canPlaceCommentDraft(commentMode, Boolean(draftAnchor), suppressPaneClick.current) || !rf.current) return;
          const point = rf.current.screenToFlowPosition({ x: event.clientX, y: event.clientY });
          setDraftAnchor({ kind: "canvas", x: point.x, y: point.y });
        }}
        onConnect={(connection: Connection) => {
          if (commentMode || markerMode) return;
          setEdges((current) => addEdge(connection, current));
          appendOnConnect(connection);
        }}
        // 可见的 + 在边界外，而真实锚点贴在边界上。扩大屏幕命中半径后，拖到 + 上即可
        // 自动吸附，不必再精确瞄准那个透明的 8px handle。
        connectionRadius={32}
        //: 线拉到空白处松手 —— 用户已经想好了「从这儿接下去」,弹一张单子让他直接选。
        //: 连到别的节点上时 isValid 为真,那是正常连线,不该弹。
        onConnectEnd={(event, connection) => {
          if (commentMode || markerMode) return;
          const instance = rf.current;
          if (!instance) return;
          const link = pendingLinkFromRelease(event, connection, instance.screenToFlowPosition);
          if (link) pending.open(link);
        }}
        onNodeDragStart={(_event, node) => beginFrameDrag(node)}
        onNodeDrag={(_event, node) => dragFrame(node)}
        onNodeDragStop={endFrameDrag}
        onInit={(instance) => {
          rf.current = instance as unknown as ReactFlowInstance;
          requestAnimationFrame(() => {
            if (viewport.saved) instance.setViewport(viewport.saved);
            else if (surface.current) {
              void fitCanvasViewport(instance, surface.current, insetsOf(surface.current), { maxZoom: 1 });
            }
            setReady(true);
          });
        }}
        //: 平移/缩放就取消待定 —— 单子钉在屏幕上、占位跟着画布走,两者会错开。
        onMoveStart={(event) => {
          if (event) cancelPending();
        }}
        onMoveEnd={(_event, next) => viewport.remember(next)}
        // 双击空白处直接加一张便签 —— 想法来的时候不该先去找按钮。
        onDoubleClick={(event) => {
          if (commentMode || markerMode) return;
          if ((event.target as HTMLElement).closest(".react-flow__node")) return;
          const instance = rf.current;
          if (!instance) return;
          const point = instance.screenToFlowPosition({ x: event.clientX, y: event.clientY });
          const item: BoardItem = {
            id: `note-${Date.now().toString(36)}`,
            kind: "note",
            x: Math.round(point.x - DEFAULT_SIZE.note.width / 2),
            y: Math.round(point.y - DEFAULT_SIZE.note.height / 2),
            ...DEFAULT_SIZE.note,
            color: "yellow",
            ...newSlotForm("note"),
          };
          setNodes((current) => [...current, ...toNodes([item])]);
        }}
        className={cn(!ready && "opacity-0", (commentMode || markerMode) && "cursor-crosshair")}
        proOptions={{ hideAttribution: false }}
        {...canvasWheelProps(inputMode)}
        zoomOnPinch
        maxZoom={2.5}
        // 删除键由 useCanvasDeleteKey 判(见下):React Flow 自带的那一套把面板按钮、Portal 出去的
        // 下拉上的 Backspace 也当成删选中的这一格。
        deleteKeyCode={null}
        nodesDraggable={!commentMode}
        nodesConnectable={!commentMode && !markerMode}
        elementsSelectable={!commentMode}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} />
        <BoardCommentLayer
          visible={commentsVisible}
          rf={rf}
          commentMode={commentMode}
          comments={comments}
          members={members}
          currentUserId={currentUserId}
          activeCommentId={activeCommentId}
          draftAnchor={draftAnchor}
          setDraftAnchor={setDraftAnchor}
          onSelectComment={onSelectComment}
          onCreateComment={onCreateComment}
          onMoveComment={onMoveComment}
          onDeleteComment={onDeleteComment}
        />
        {/* 缩放钮/预览图**不吃应用主题**(xyflow 默认一律白底)—— 深色下就是右下角一块白。
            把 --xy-* 映射到设计令牌,和工作流页用的是同一套(见 WorkflowsView 里那段说明)。 */}
        {showMinimap && <MiniMap
          pannable
          zoomable
          position="bottom-right"
          //: **有面板打开时缩略图让开。** 面板挂在节点层(react-flow__renderer 的叠放上下文)里,缩略图是它上面一层的
          //: 浮层,位置一重叠就压在面板的发送键上 —— 调层级做不到只让面板盖过它(节点也会跟着盖过去)。打开一格的面板
          //: 时人在改这一格、不在找位置,缩略图淡出、不接点击,关掉面板就回来。
          className={cn(
            "overflow-hidden rounded-md border border-border transition-opacity duration-150",
            composerShown && "pointer-events-none opacity-0",
          )}
          bgColor="var(--panel)"
          maskColor="color-mix(in srgb, var(--background) 55%, transparent)"
          nodeColor="var(--border-strong)"
          nodeStrokeColor="transparent"
        />}
      </ReactFlow>
      </SequenceAddContext.Provider>
      </MarkerEditorProvider>

      {markerMode && <AnnotationModeHint kind="marker" onExit={onExitMarkerMode} />}
      {commentMode && (
        <BoardCommentModeHint onExit={onExitCommentMode} />
      )}


      {/* 拖着文件悬在上面时的提示。**盖住整块**,虚线只收在中间那段字上。 */}
      {(drop.active || uploading) && (
        <div className="pointer-events-none absolute inset-0 z-40 grid place-items-center bg-[color-mix(in_oklab,var(--primary)_10%,var(--background))]">
          <span className="grid justify-items-center gap-2 rounded-lg border-2 border-dashed border-primary px-6 py-4 text-ui-md font-semibold text-primary">
            {uploading ? <Loader2 size={20} className="animate-spin" /> : <FileUp size={20} />}
            {t(uploading ? "boardUploading" : "boardDropHere")}
          </span>
        </div>
      )}

      {/* 从线尾长出下一个节点:占位和待定的线已经画在画布里(见 display),这里是挂在占位旁边的单子。 */}
      {pendingLink && (
        <PendingLinkMenu
          title={t("boardSpawnTitle")}
          kinds={linkChoices}
          describe={describeChoice}
          active={pending.active}
          onActiveChange={pending.setActive}
          onChoose={pending.choose}
          onCancel={cancelPending}
          ghostSize={PENDING_GHOST_SIZE}
          link={pendingLink}
        />
      )}

      {/* 选中之后才出操作条 —— 没选中时它没有作用对象。 */}
      <ItemToolbar
        nodes={nodes}
        setNodes={setNodes}
        onRemoveSelected={removeSelected}
        onCopySelected={copySelection}
        onRename={commentMode || markerMode ? undefined : setRenaming}
        onPickAsset={onPickAsset}
        onPickDocument={commentMode || markerMode || !workspaceId ? undefined : setPickingDocument}
        saveToNote={commentMode || markerMode || !workspaceId ? undefined : { workspaceId, boardId }}
        onSpawn={onRun ? spawnLinked : undefined}
        producers={producers}
        panel={panel}
        onPanel={onRun && !commentMode && !markerMode ? togglePanel : undefined}
      />

      {workspaceId && <NotePickerDialog workspaceId={workspaceId} open={!!pickingDocument} onOpenChange={open => { if (!open) setPickingDocument(null); }} onPick={note => { if (pickingDocument) patch(pickingDocument, {note_id: note.id, note_revision: note.revision, text: note.title}); }}/>}
      {composerItem && producer && feeding.blocked && <NodeToolbar nodeId={composerItem.id} isVisible position={Position.Bottom} offset={BOARD_NODE_PANEL_OFFSET}><div role={feeding.pending ? "status" : "alert"} className={cn(CANVAS_WINDOW_SURFACE_CLASS, "max-w-sm px-4 py-3 text-ui-sm text-muted-foreground")}>{t(feeding.pending ? "documentLoading" : "documentBlocked")}</div></NodeToolbar>}

      {/* 剪一段:定起止,产出落到**新节点**上。 */}
      {trimming && onRun && (() => {
        const node = nodes.find((one) => one.id === trimming);
        const item = node && (node.data as unknown as { item: BoardItem }).item;
        if (!node || !item?.asset_id || (item.kind !== "video" && item.kind !== "audio")) return null;
        return (
          <TrimComposer
            key={item.id}
            item={{ ...item, kind: item.kind }}
            assetId={item.asset_id as string}
            workspaceId={workspaceId}
            busy={false}
            //: 取一帧和剪一段都产出**新的一格** —— 摆在原件下面,原件不动。
            onGrabFrame={onGrabFrame ? (at) => void onGrabFrame({
              assetId: item.asset_id as string,
              at,
              x: node.position.x,
              y: node.position.y + (node.height ?? 200) + 60,
            }) : undefined}
            onTrim={({ start, end, mute }) => {
              void onRun({
                producer: "trim",
                //: 产出落到**新的一格**,摆在原件下面 —— 覆盖原件的话,上一版就没了。
                item_id: `${item.kind}-${Date.now().toString(36)}`,
                kind: item.kind,
                x: node.position.x,
                y: node.position.y + (node.height ?? 200) + 60,
                form: { asset_id: item.asset_id as string, start, end, mute },
              }).finally(() => setPanel(null));
            }}
          />
        );
      })()}

      {/* 选中的那一格还等着产出:挂它的产出者的面板(一张表,见 boardComposers)。 */}
      {!feeding.blocked && composerItem && producer && onRun && renderComposer(producer, {
        item: composerView(composerItem),
        position: nodes.find((one) => one.id === composerItem.id)?.position ?? { x: composerItem.x, y: composerItem.y },
        workspaceId,
        feeding,
        documents,
        models: models ?? [],
        writing: writing === composerItem.id,
        setWriting,
        onFormChange: (form) => patch(composerItem.id, { form: withProducer(form, producer, composerItem.form) }),
        onPickAsset,
        run: onRun,
        producers,
      })}
      {/* 操作条上点开的一项能力:它的面板换下这一格自己的那块。宿主就是这一格,设置存在它的 `form.abilities` 上。 */}
      {!feeding.blocked && composerItem && ability && onRun && renderAbility(ability, {
        item: composerItem,
        position: nodes.find((one) => one.id === composerItem.id)?.position ?? { x: composerItem.x, y: composerItem.y },
        workspaceId,
        feeding,
        documents,
        models: models ?? [],
        writing: false,
        setWriting,
        onSave: (setting) => patch(composerItem.id, { form: withAbility(composerItem.form, ability, setting) }),
        onPickAsset,
        run: onRun,
        producers,
      })}
    </div>
  );
}

export function BoardCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <Inner {...props} />
    </ReactFlowProvider>
  );
}
