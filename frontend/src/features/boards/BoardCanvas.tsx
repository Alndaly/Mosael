import { CANVAS_WINDOW_SURFACE_CLASS } from "@/components/app/canvasPanelLayout";
import { CommentCard } from "@/features/collaboration/CommentCard";
import { AnnotationModeHint } from "@/features/markers/AnnotationModeHint";
import { NO_UPSTREAM, upstreamOf } from "./boardUpstream";
import { useQueries } from "@tanstack/react-query";
import { toast } from "sonner";
import { getNoteReference, noteReferenceQuery } from "@/api/domains/notes";
import { NotePickerDialog } from "@/features/notes/NotePickerDialog";
import { type BoardDocumentState } from "./boardDocumentSources";
import { useCanvasInputMode } from "@/components/app/canvasInputMode";
import React from "react";
import { carriedByFrame } from "@/features/boards/frameCarry";
import {
  Background,
  BackgroundVariant,
  MiniMap,
  ReactFlow,
  NodeToolbar,
  Position,
  ReactFlowProvider,
  ViewportPortal,
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
import { Copy, FileUp, Group, Loader2, Maximize2, MessageSquare, PencilLine, Replace, Scissors, Sparkles, Trash2 } from "lucide-react";

import { assetFileUrl, assetPreviewUrl, type CollaborationComment, type WorkspaceMember } from "@/api/client";
import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { useImagePreview } from "@/components/app/image-preview";
import { centerCanvasViewport, fitCanvasViewport, visibleCanvasSize, type CanvasViewportInsets } from "@/components/app/fitCanvasViewport";
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

import { isNodeProducer, type BoardCanvas as Canvas, type BoardItem, type BoardProducer, type BoardProducerInfo, type BoardRunRequest, type GenerationOption } from "@/api/client";
import { boardToolFace, boardToolOptions, toolCellSize } from "@/features/boards/boardTools";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { errorText } from "@/api/errorMessage";
import { isMediaFile, useFileDrop } from "@/lib/useFileDrop";
import { usePersistentViewport } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";
import { isCanvasKeyTarget, listenKeys } from "@/lib/shortcuts";
import { canRedo, canUndo, emptyHistory, record, redo, undo } from "@/features/boards/canvasHistory";
import { TrimComposer } from "@/features/boards/TrimComposer";
import { canAskWriter, composerOnDemand, renderComposer, slotProducers } from "@/features/boards/boardComposers";
import { BOARD_NODE_TYPES, DEFAULT_SIZE, NOTE_COLORS, noteColorClass , isMediaKind, kindIcon, kindText, SPAWNABLE_KINDS, type BoardToolFace, type MediaKind } from "@/features/boards/boardNodes";
import { composerView, copiedItem, itemIsRunning, newSlotForm, producerOf, withProducer } from "@/features/boards/boardItemState";
import { useKeepInCanvas } from "@/features/boards/BoardComposerShell";
import { BOARD_NODE_PANEL_OFFSET } from "@/features/boards/boardLayout";
import { assetItem, clipboardContent, type PlacedAsset } from "@/features/boards/boardPlacement";
import { useCanvasDeleteKey } from "@/components/app/useCanvasDeleteKey";
import { CommentComposer, type CommentDraft } from "@/features/collaboration/CommentComposer";
import { MarkerPin } from "@/features/markers/MarkerPin";
import { MarkerEditorProvider } from "@/features/markers/MarkerEditorProvider";
import {
  MARKER_PREFIX,
  MAX_MARKERS,
  newMarkerId,
  nextMarkerName,
  toMarkerNodes,
  type CanvasMarker,
} from "@/features/markers/markers";
import { useMarkerShortcuts } from "@/features/markers/useMarkerShortcuts";

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

/**
 * 这块画布的层次 —— **一处说了算**。
 *
 * 规则是"旗子压在所有内容之上"。它此前是调用处一个凭手感挑的 `zIndex: 2`,而工作流那块画布
 * 写的是 950:两个数不是谁错了,是同一条规则在两边各挑了一个常数,而规则本身没写在任何地方。
 * 加一种新节点类型时,该挑几没有参照系可查。
 */
const LAYERS = {
  /** 分组框永远在最底 —— 它是背景,盖住上面的项就没法点了。 */
  frame: 0,
  /**
   * 连线夹在分组框和项之间。在框之下的话(此前就是:两者都是 0,而 React Flow 把节点那层排在
   * 连线之后),框那层 3% 的底色和虚线边框就压在线上,线一穿过框就像被切了一刀;在项之上的话,
   * 线头会压住卡片。夹在中间:线完整地画在框上面,两头钻进卡片底下,箭头尖顶在卡片边框上。
   */
  edge: 1,
  item: 2,
  /** 一枚贴在画布上的旗子,被别的东西盖住就点不到了。 */
  marker: 3,
  /** 拉线松手时的占位和那根待定的线:它说的是「新的一格会落在这儿」,被已有的项盖住就等于没说。 */
  pending: 4,
} as const;

function toNodes(items: BoardItem[]): Node[] {
  return items.map((item) => ({
    id: item.id,
    type: item.kind,
    position: { x: item.x, y: item.y },
    width: item.width ?? DEFAULT_SIZE[item.kind].width,
    height: item.height ?? DEFAULT_SIZE[item.kind].height,
    data: { item },
    zIndex: item.kind === "frame" ? LAYERS.frame : LAYERS.item,
  }));
}

/** 把 React Flow 的当前状态汇成要存的画布。**位置以 React Flow 为准** —— 它才是刚被拖过的那份。 */
export function toCanvas(nodes: Node[], edges: Edge[]): Canvas {
  // 标记不是画板项,也连不了线 —— 所以它不进这张表。
  const alive = new Set(nodes.filter((node) => node.type !== "marker").map((node) => node.id));
  return {
    items: nodes
      .filter((node) => node.type !== "marker")
      .map((node) => {
        const { item } = node.data as unknown as { item: BoardItem };
        return {
          ...item,
          x: Math.round(node.position.x),
          y: Math.round(node.position.y),
          width: Math.round(node.width ?? node.measured?.width ?? DEFAULT_SIZE[item.kind].width),
          height: Math.round(node.height ?? node.measured?.height ?? DEFAULT_SIZE[item.kind].height),
        };
      }),
    /*
     * **不放出悬空的线。** 后端校验「连线两端必须都是画板上的项」,一根指向已删节点的线会让
     * **整张画板存不下去** —— 用户看到的是「画板没能保存」,而画面上那个节点早就不见了,
     * 根本联想不到是它。删除按钮那条路已经一并删线(见 removeSelected),这里是最后一道:
     * 序列化是唯一知道 items 和 edges 全貌的地方,别的路径再漏一次也漏不出去。
     */
    edges: edges
      .filter((edge) => alive.has(edge.source) && alive.has(edge.target))
      .map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })),
    // 标记单独一份,不混进 items —— 它没有素材、不生成、连不了线,混进去的话每一处遍历
    // items 的地方(生成、导出、缩略图、连线校验)都要先分辨一次"这个是不是标记"。
    markers: nodes
      .filter((node) => node.type === "marker")
      .map((node) => ({
        ...(node.data as unknown as { marker: CanvasMarker }).marker,
        x: Math.round(node.position.x),
        y: Math.round(node.position.y),
      })),
  };
}

/**
 * 画布上的**画板项**。标记不是画板项 —— 它的 data 里没有 `item`。
 *
 * **只此一处。** 直接对全部节点 `node.data.item` 遍历的地方,加了标记之后就是一次崩溃:
 * 读到的是 undefined,下一句 `.kind` 当场抛,而抛在派生里就是整张画板白屏 ——
 * 加一枚标记,这张画板就再也打不开了。收成一个函数,是为了让"标记没有 item"只需要被记住一次。
 */
export function boardItems(nodes: Node[]): BoardItem[] {
  return nodes
    .filter((node) => node.type !== "marker")
    .map((node) => (node.data as unknown as { item: BoardItem }).item);
}

/**
 * 复制选中的几项:换新 id、错开一点放,复制出来的那几项成为新的选中。
 *
 * **一起复制的几项之间的线也跟着复制**,两端接到新的那几格上 —— 一张便签连着一个图片槽,
 * 复制这一对是想要「同一套再来一份」;线不跟着来的话,副本里的图片槽拿不到那段提示词,
 * 那条线表达的关系就丢了。连着没被选中那项的线不跟着来:那一端没有副本可接。
 *
 * 每一格按 copiedItem 复制(进行中的运行态不带过去)。
 */
export function copySelected(nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[] } {
  // 标记也可能被选中(它在画布上就是一个节点),但它没有 item —— 而且"复制一枚旗子"
  // 本来也不成立:两枚指着同一处的标记不表达任何东西。
  const picked = nodes.filter((node) => node.selected && node.type !== "marker");
  const renamed = new Map<string, string>();
  const copies = picked.map((node) => {
    const source = (node.data as unknown as { item: BoardItem }).item;
    const copy = copiedItem(source, `${source.kind}-${Math.random().toString(36).slice(2, 9)}`);
    renamed.set(node.id, copy.id);
    return {
      ...node,
      id: copy.id,
      // 错开一点放,不然复制出来的正好盖在原件上,看着像什么都没发生。
      position: { x: node.position.x + 24, y: node.position.y + 24 },
      selected: true,
      data: { ...node.data, item: copy },
    };
  });
  const copiedEdges = edges.flatMap((edge) => {
    const source = renamed.get(edge.source);
    const target = renamed.get(edge.target);
    return source && target ? [{ id: `${edge.id}-${source}-${target}`, source, target }] : [];
  });
  //: 槽位里顺着线挂上的那几份跟着线走:上游也一起复制了的,出处改记成新的那一格(线也复制了);
  //: 没一起复制的,副本上没有那根线,存的时候服务端把它摘掉 —— 和删掉那根线是同一条规则。
  const rewired = copies.map((node) => {
    const item = (node.data as unknown as { item: BoardItem }).item;
    const sources = item.form?.source_assets;
    if (!sources?.some((one) => one.from && renamed.has(one.from))) return node;
    const source_assets = sources.map((one) =>
      one.from && renamed.has(one.from) ? { ...one, from: renamed.get(one.from) } : one,
    );
    return { ...node, data: { ...node.data, item: { ...item, form: { ...item.form, source_assets } } } };
  });
  return {
    nodes: [...nodes.map((node) => ({ ...node, selected: false })), ...rewired],
    edges: [...edges, ...copiedEdges],
  };
}

/** 一次普通点击的选择结果。显式收口，避免 React Flow 的内部选择事件与受控 nodes 回写竞态。 */
export function focusBoardNode(nodes: Node[], nodeId: string): Node[] {
  let changed = false;
  const next = nodes.map((node) => {
    const selected = node.id === nodeId;
    if (Boolean(node.selected) === selected) return node;
    changed = true;
    return { ...node, selected };
  });
  return changed ? next : nodes;
}

/** A draft is a transient editor, not a canvas selection. Keep it stable until it is submitted or
 * cancelled so clicks used to focus/type cannot silently move it to a new anchor. */
export function canPlaceCommentDraft(
  commentMode: boolean,
  hasDraft: boolean,
  gestureMoved = false,
  dismissedActiveComment = false,
): boolean {
  return commentMode && !hasDraft && !gestureMoved && !dismissedActiveComment;
}

export function canMoveComment(authorId: string | null | undefined, currentUserId: string | null | undefined): boolean {
  return Boolean(authorId && currentUserId && authorId === currentUserId);
}

type CanvasCommentAnchor = NonNullable<CollaborationComment["anchor"]>;
type ScreenPoint = { x: number; y: number };

/** Keep comment movement stable at every zoom level by measuring the pointer delta in flow space. */
export function moveCommentAnchorByScreenDelta(
  anchor: CanvasCommentAnchor,
  startScreen: ScreenPoint,
  currentScreen: ScreenPoint,
  screenToFlowPosition: (point: ScreenPoint) => ScreenPoint,
): CanvasCommentAnchor {
  const start = screenToFlowPosition(startScreen);
  const current = screenToFlowPosition(currentScreen);
  return {
    ...anchor,
    x: (anchor.x ?? 0) + current.x - start.x,
    y: (anchor.y ?? 0) + current.y - start.y,
  };
}

export function shouldDismissCommentOverlay(
  hasActiveComment: boolean,
  hasDraft: boolean,
  pointerInsideOverlay: boolean,
): boolean {
  return (hasActiveComment || hasDraft) && !pointerInsideOverlay;
}

export function shouldSuppressCommentPlacement(gesture: {
  moved: boolean;
  dismissedActive: boolean;
  startedInsideOverlay: boolean;
  endedInsideOverlay: boolean;
}): boolean {
  return gesture.moved
    || gesture.dismissedActive
    || (gesture.startedInsideOverlay && !gesture.endedInsideOverlay);
}

/**
 * 查找节点跳过去时的缩放:至少拉到 0.9(看得清字),节点大到放不下时退到刚好装得下、四周留一圈;
 * 不超过画布的最大缩放。已经比 0.9 更近、而且装得下时保持原样 —— 用户自己拉近的,别替他拉远。
 */
export function searchFocusZoom(
  current: number,
  size: { width: number; height: number },
  visible: { width: number; height: number },
  maxZoom = 2.5,
): number {
  const fit = Math.min(visible.width / (size.width * 1.25), visible.height / (size.height * 1.25));
  return Math.min(Math.max(current, 0.9), fit, maxZoom);
}

export function BoardCommentModeHint({ onExit }: { onExit?: () => void }) {
  return <AnnotationModeHint kind="comment" onExit={onExit} />;
}

interface Props {
  boardId: string;
  /** 提示词面板里 `@` 引用素材时去哪个工作区找。 */
  workspaceId: string;
  canvas: Canvas;
  onChange: (canvas: Canvas) => void;
  /** 让上层开素材选择器。kind 决定它列图片还是视频 —— 选得到的就该是贴上去能看的。 */
  onPickAsset: (kind: MediaKind, place: (assetId: string) => void) => void;
  /**
   * 在某一格上跑一个产出者(生成、写字、念出来、截一段)。上层拿得到 workspaceId 和接口,画布只
   * 提供「落在哪一格」和「表单是什么」。写字同步返回,其余摆好占位就回、产出由回执填回来。
   */
  onRun?: (request: BoardRunRequest) => Promise<unknown>;
  /** 取某一帧,存成一份新素材、落到一个新节点上 —— 原素材不动。 */
  onGrabFrame?: (input: { assetId: string; at: number; x: number; y: number }) => Promise<unknown>;
  /** 可用的生成模型 —— 提示词面板要让人选。 */
  models?: GenerationOption[];
  /** 这个人能用的产出者(后端 GET /api/boards/producers):工具格的表单、拉线菜单里的「工具」一组、
   *  空槽在几个产出者之间的切换都照它。还没到是 undefined。 */
  producers?: BoardProducerInfo[];
  /** 停下某一格正在跑的任务(工具格上的停止按钮)。 */
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

function Inner({ boardId, workspaceId, canvas, onChange, onPickAsset, onRun, onGrabFrame, models, producers, onStop, showMinimap = true, edgeShape = "default", searchHighlight = null, onDropFiles, uploading, getInsets, commentMode = false, markerMode = false, markersVisible = true, commentsVisible = true, comments = [], members = [], currentUserId, activeCommentId, onSelectComment, onCreateComment, onMoveComment, onDeleteComment, onExitCommentMode, onExitMarkerMode, onReady }: Props) {
  const [inputMode] = useCanvasInputMode();
  const t = useI18n();
  const rf = React.useRef<ReactFlowInstance | null>(null);
  const surface = React.useRef<HTMLDivElement | null>(null);
  //: Backspace / Delete 只删冲着画布来的那一下 —— 和工作流编辑器同一个钩子。实例从 Provider 取,
  //: 不等 onInit:删除键在画布挂上的那一刻就该认。
  const flow = useReactFlow();
  const flowRef = React.useRef(flow);
  flowRef.current = flow;
  useCanvasDeleteKey(surface, flowRef);
  const viewport = usePersistentViewport(`board:${boardId}`);
  const [ready, setReady] = React.useState(false);
  const [draftAnchor, setDraftAnchor] = React.useState<NonNullable<CollaborationComment["anchor"]> | null>(null);
  const [commentPositions, setCommentPositions] = React.useState<Record<string, { x: number; y: number }>>({});
  const paneGesture = React.useRef<{
    x: number;
    y: number;
    moved: boolean;
    dismissedActive: boolean;
    startedInsideOverlay: boolean;
  } | null>(null);
  const suppressPaneClick = React.useRef(false);
  const commentDrag = React.useRef<{
    id: string;
    pointerId: number;
    startScreen: { x: number; y: number };
    origin: { x: number; y: number };
    nodeId?: string;
    moved: boolean;
    last?: { x: number; y: number };
  } | null>(null);
  const draftCommentDrag = React.useRef<{
    pointerId: number;
    startScreen: ScreenPoint;
    origin: CanvasCommentAnchor;
    moved: boolean;
  } | null>(null);
  const suppressCommentClick = React.useRef<string | null>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState([...toNodes(canvas.items), ...toMarkerNodes(canvas.markers ?? [], LAYERS.marker)]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(
    canvas.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })),
  );

  React.useEffect(() => {
    if (!commentMode) setDraftAnchor(null);
    else setNodes((current) => current.map((node) => (node.selected ? { ...node, selected: false } : node)));
  }, [commentMode, setNodes]);
  React.useEffect(() => { setNodes(current => current.map(node => ({ ...node, selected: false }))); }, [markerMode, markersVisible, setNodes]);

  React.useEffect(() => {
    if (!shouldDismissCommentOverlay(Boolean(activeCommentId), Boolean(draftAnchor), false)) return;
    const dismissOnOutsidePointer = (event: PointerEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      const insideOverlay = Boolean(target?.closest("[data-board-comment-overlay], [data-suggestion-menu]"));
      if (!shouldDismissCommentOverlay(Boolean(activeCommentId), Boolean(draftAnchor), insideOverlay)) return;
      if (activeCommentId) onSelectComment?.(null);
      if (draftAnchor) setDraftAnchor(null);
    };
    document.addEventListener("pointerdown", dismissOnOutsidePointer, true);
    return () => document.removeEventListener("pointerdown", dismissOnOutsidePointer, true);
  }, [activeCommentId, draftAnchor, onSelectComment]);

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


  // 每次画布变了就汇一份给上层去存。**用 JSON 比对而不是引用比对** —— React Flow 每次
  // 拖动都换新对象,引用比对等于每帧都报"变了"。
  //: 选中的那个空槽/生成中的槽 —— 只有一个被选中时才挂面板,多选没有单一的作用对象。
  /** 选中的**还空着**的那一项 —— 空槽就是「等着被填」,面板挂在它下面。 */
  const [pickingDocument, setPickingDocument] = React.useState<string | null>(null);
  const [refreshingDocument, setRefreshingDocument] = React.useState<string | null>(null);
  const documentItems = boardItems(nodes).filter(item => item.kind === "document");
  const documentQueries = useQueries({queries: documentItems.map(item => noteReferenceQuery(workspaceId ?? "", item.note_id ?? "", item.note_revision))});
  const documents = new Map<string, BoardDocumentState>(documentItems.map((item, index) => [item.id, {
    reference: documentQueries[index].data, pending: !!item.note_id && documentQueries[index].isPending,
    error: documentQueries[index].error?.message,
  }]));
  const refreshDocument = async (id: string) => {
    const item = documentItems.find(item => item.id === id);
    if (!item?.note_id || !workspaceId) return;
    setRefreshingDocument(id);
    try {
      const reference = await getNoteReference(workspaceId, item.note_id);
      setNodes(current => current.map(node => {
        const currentItem = (node.data as {item: BoardItem}).item;
        // A delayed request must not replace a different note chosen in the meantime.
        return node.id === id && currentItem.note_id === item.note_id ? {...node, data: {...node.data, item: {...currentItem, text: reference.title, note_revision: reference.revision}}} : node;
      }));
    } catch (error) { toast.error(errorText(error)); }
    finally { setRefreshingDocument(null); }
  };
  //: 选中的那一格底下挂哪个产出者的面板 —— 规则在 producerOf,这里只认「选中了一格」。
  const composerItem = React.useMemo(() => {
    const picked = nodes.filter((node) => node.selected && node.type !== "marker");
    if (picked.length !== 1) return null;
    return (picked[0].data as unknown as { item: BoardItem }).item;
  }, [nodes]);
  //: 哪一张便签打开了「让 AI 写」。**写字的面板按需挂**(composerOnDemand):便签首先是自己写的字,
  //: 选中它多半是要挪一挪 —— 此前一选中就弹出写作面板,挪一张便签也要先把它关掉。换选别的就收起。
  const [writerFor, setWriterFor] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (writerFor && composerItem?.id !== writerFor) setWriterFor(null);
  }, [writerFor, composerItem]);
  const slotProducer = composerItem ? producerOf(composerItem) : null;
  const producer =
    slotProducer && (!composerOnDemand(slotProducer) || (writerFor === composerItem?.id && composerItem && canAskWriter(composerItem)))
      ? slotProducer
      : null;

  /**
   * 连到这个节点上的上游产出,按连线的先后。
   *
   * **这就是那条线的意思。** 连了线还要再挂一遍素材的话,线就只是根装饰;所以这里把上游
   * 已经出了产出的项收上来,交给面板照当前生成方式挂进槽位(一张图当首帧、多张当参考)。
   * 还没出产出的上游跳过 —— 它自己都还没有东西可给。
   */
  //: 截取面板照着表单上记下的那份素材截,不吃上游 —— 只有吃上游的几块面板才去算、才会被取不到的
  //: 上游文档拦住。
  const feeding = composerItem && producer && producer !== "trim"
    ? upstreamOf(composerItem.id, boardItems(nodes), edges, documents)
    : NO_UPSTREAM;

  /**
   * 拖动分组框时被它带着走的那几项。
   *
   * **在按下的那一刻定下来,拖的过程中不再变。** 边拖边判「谁在框里」的话,框扫过谁就会
   * 顺手把谁卷走 —— 用户只是想把这一组挪到右边,结果沿途的东西全被推到了一起。
   */
  const carried = React.useRef<{ id: string; from: { x: number; y: number } }[]>([]);
  const dragFrom = React.useRef<{ x: number; y: number } | null>(null);

  const beginFrameDrag = React.useCallback(
    (node: Node) => {
      const item = (node.data as unknown as { item?: BoardItem }).item;
      carried.current = [];
      dragFrom.current = null;
      // 标记节点没有 item(它不是画板项)—— 不先问一句,拖一枚旗子就会在这里抛。
      if (!item || item.kind !== "frame" || !item.move_children) return;
      const left = node.position.x;
      const top = node.position.y;
      const right = left + (node.width ?? DEFAULT_SIZE.frame.width);
      const bottom = top + (node.height ?? DEFAULT_SIZE.frame.height);
      dragFrom.current = { ...node.position };
      //: 判定规则在 frameCarry.ts —— 它是一条规则不是渲染,而它出过一个只有嵌套时
      //: 才看得见的错(外框把内框里的东西带走了,却把内框留在原地)。
      const positions = new Map(nodes.map((one) => [one.id, one.position]));
      carried.current = carriedByFrame(
        { id: node.id, kind: "frame", x: left, y: top, width: right - left, height: bottom - top },
        nodes.map((one) => ({
          id: one.id,
          kind: String(one.type ?? ""),
          x: one.position.x,
          y: one.position.y,
          width: one.width ?? 0,
          height: one.height ?? 0,
        })),
      ).map((one) => ({ id: one.id, from: { ...(positions.get(one.id) ?? { x: one.x, y: one.y }) } }));
    },
    [nodes],
  );

  const dragFrame = React.useCallback(
    (node: Node) => {
      const from = dragFrom.current;
      if (!from || carried.current.length === 0) return;
      //: 位移始终从**按下时**的位置算起,不是上一帧 —— 逐帧累加的话,某一帧被丢掉
      //: (拖得快时会)就永久错开一段。
      const dx = node.position.x - from.x;
      const dy = node.position.y - from.y;
      const moves = new Map(carried.current.map((one) => [one.id, one.from]));
      setNodes((current) =>
        current.map((one) => {
          const origin = moves.get(one.id);
          return origin ? { ...one, position: { x: origin.x + dx, y: origin.y + dy } } : one;
        }),
      );
    },
    [setNodes],
  );

  // ── 标记(位置书签)────────────────────────────────────────────────────────
  //: 事实来源和画板项一样是 React Flow 的 nodes —— 拖动、选中、⌫ 删除因此全是白拿的,
  //: 撤销/重做也一样(历史存的是整份 toCanvas 快照,里面本来就带着 markers)。
  //: **经序列化取回一份稳定引用。** 这份清单要交给工具条(见 onReady 那条 effect),而
  //: `nodes` 每拖一帧就换一次身份 —— 直接 map 出来的话,拖任何一个节点都会让工具条跟着
  //: 重挂一遍。标记至多几十个,序列化的代价远小于每帧一次的重渲染。
  const markerKey = React.useMemo(
    () => JSON.stringify(nodes.filter((node) => node.type === "marker").map((node) => ({
      ...(node.data as unknown as { marker: CanvasMarker }).marker,
      x: Math.round(node.position.x),
      y: Math.round(node.position.y),
    }))),
    [nodes],
  );
  const markers = React.useMemo(() => JSON.parse(markerKey) as CanvasMarker[], [markerKey]);

  const patchMarker = React.useCallback((next: CanvasMarker) => {
    setNodes((current) =>
      current.map((node) => (node.id === MARKER_PREFIX + next.id ? { ...node, data: { ...node.data, marker: next } } : node)),
    );
  }, [setNodes]);

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

  const deleteMarker = React.useCallback((id: string) => {
    setNodes((current) => current.filter((node) => node.id !== MARKER_PREFIX + id));
  }, [setNodes]);

  /** 画布上没被右栏盖住的那块。页面没给就是整块。 */
  const insetsOf = React.useCallback(
    (pane: HTMLElement): CanvasViewportInsets => getInsets?.(pane) ?? {},
    [getInsets],
  );

  /**
   * 把一个流坐标点摆到**看得见的那块**的正中。
   *
   * 不是 `instance.setCenter` —— 它照整块画布居中,而右栏的智能体是盖在画布上的:
   * 目标正好落在它底下,看着像"点了没反应"。跳标记、跳评论都从这里走。
   */
  const centerOn = React.useCallback((point: { x: number; y: number }) => {
    const instance = rf.current;
    const pane = surface.current;
    if (!instance || !pane) return;
    void centerCanvasViewport(instance, pane, point, insetsOf(pane), {
      zoom: Math.max(instance.getZoom(), 0.9),
      duration: 350,
    });
  }, [insetsOf]);

  /** 跳到某个标记。视口居中过去,不改选中态 —— 跳转是"我要看那儿",不是"我要改那个"。 */
  const jumpToMarker = React.useCallback((marker: CanvasMarker) => {
    // 加半枚旗子:节点坐标是左上角,照它居中的话旗子整个偏在右下。
    centerOn({ x: marker.x + 60, y: marker.y + 14 });
  }, [centerOn]);

  useMarkerShortcuts(markers, jumpToMarker, !commentMode);

  /** 查找节点跳到某一项。和跳标记一样只动视口、不改选中态 —— 按 Enter 一路往下看的时候,
   *  每一格都弹出自己的面板会把画布盖满。 */
  const focusItem = React.useCallback((itemId: string) => {
    const instance = rf.current;
    const pane = surface.current;
    const node = instance?.getNode(itemId);
    if (!instance || !pane || !node) return;
    const size = {
      width: node.measured?.width ?? node.width ?? 200,
      height: node.measured?.height ?? node.height ?? 120,
    };
    const insets = insetsOf(pane);
    void centerCanvasViewport(
      instance,
      pane,
      { x: node.position.x + size.width / 2, y: node.position.y + size.height / 2 },
      insets,
      {
        zoom: searchFocusZoom(instance.getZoom(), size, visibleCanvasSize(pane.clientWidth, pane.clientHeight, insets)),
        duration: 350,
      },
    );
  }, [insetsOf]);

  /** 在当前视口中心放一枚标记。放在**看得见的地方**:标记标的是"我现在在看的这块地方"。 */
  const addMarker = React.useCallback((point?: { x: number; y: number }) => {
    const instance = rf.current;
    const pane = surface.current;
    if (!instance || !pane) return;
    let placed = false;
    setNodes((current) => {
      const existing = current
        .filter((node) => node.type === "marker")
        .map((node) => (node.data as unknown as { marker: CanvasMarker }).marker);
      if (existing.length >= MAX_MARKERS) return current;
      // 同样避开右栏:一枚落在智能体底下的标记,加完就看不见。
      const rect = pane.getBoundingClientRect();
      const visible = visibleCanvasSize(pane.clientWidth, pane.clientHeight, insetsOf(pane));
      const center = point ?? instance.screenToFlowPosition({
        x: rect.left + visible.left + visible.width / 2,
        y: rect.top + visible.top + visible.height / 2,
      });
      const marker: CanvasMarker = {
        id: newMarkerId(existing),
        name: nextMarkerName(t("markers"), existing),
        x: Math.round(center.x),
        y: Math.round(center.y),
      };
      placed = true;
      return [...current.map((node) => ({ ...node, selected: false })), ...toMarkerNodes([marker], LAYERS.marker).map((node) => ({ ...node, selected: true }))];
    });
    if (!placed) toast.error(t("markerLimit").replace("{n}", String(MAX_MARKERS)));
  }, [setNodes, t, insetsOf]);

  /** 工具格上显示的那几样,从产出者清单里查。清单没到是 undefined;查不到(插件卸了、没有连接)是 null。
   *  「接没接上」看的是此刻连进来的那几格(和面板同一份:按连线的先后)。 */
  const itemsById = new Map(boardItems(nodes).map((item) => [item.id, item]));
  const toolFace = (item: BoardItem): BoardToolFace | null | undefined => {
    if (producers === undefined) return undefined;
    const found = producers.find((one) => one.id === item.form?.producer);
    if (!found) return null;
    const sources = edges
      .filter((edge) => edge.target === item.id)
      .map((edge) => itemsById.get(edge.source))
      .filter((one): one is BoardItem => Boolean(one));
    return boardToolFace(found, item, sources);
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
          data: { ...node.data, onText: setText, onAspect: setAspect, renaming: renaming === node.id, onRenaming: setRenaming, onRename: setTitle, commentMode: commentMode || markerMode, workspaceId, boardId, document: documents.get(node.id), onPickDocument: setPickingDocument, onRefreshDocument: refreshDocument, refreshingDocument: refreshingDocument === node.id,
            //: 停止属于运行态的外壳:每一种在跑的格子都有(生成、念、写、截、工具),不只工具格。
            onStop,
            ...(node.type === "action" ? { tool: toolFace((node.data as unknown as { item: BoardItem }).item) } : {}) },
        },
  );
  //: 箭头、命中宽度、层次都是**画出来的那一份**才有的东西,不进画布数据(toCanvas 只存 id 和两头)。
  const baseEdges: Edge[] = shapeEdges(edges, edgeShape).map((edge) => ({
    ...edge,
    ...CANVAS_EDGE_OPTIONS,
    zIndex: LAYERS.edge,
    selectable: !commentMode && !markerMode,
  }));

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

  const stepBack = React.useCallback(() => {
    setHistory((current) => {
      const next = undo(current);
      if (!next) return current;
      restore(next.present);
      return next;
    });
  }, [restore]);

  const stepForward = React.useCallback(() => {
    setHistory((current) => {
      const next = redo(current);
      if (!next) return current;
      restore(next.present);
      return next;
    });
  }, [restore]);

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
      //: 工具格和它要产出的那种内容格一样大(一个出图的工具是一块图片格那么大,见 boardTools.toolCellSize)。
      const producerId = extra.form?.producer;
      const size = isNodeProducer(producerId)
        ? toolCellSize(producers?.find((one) => one.id === producerId))
        : DEFAULT_SIZE[kind];
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
    [setNodes, setText, setAspect, producers],
  );

  /**
   * 从节点拉出一条线、松手在空白处时弹的那个菜单。
   *
   * **拉了线就说明用户已经想好了「从这儿接下去」**,这时再让他去右上角找按钮加节点、
   * 拖回来、连上,是把一个动作拆成了三个。菜单里选一种,节点就落在松手的地方并且线已经连好。
   */
  //: 正在给哪一项定剪辑范围。**不是选中就弹** —— 「剪一段」是对已有产出的动作,
  //: 而选中一段片子最常见的意图是看它、拖它,不是剪它。
  const [trimming, setTrimming] = React.useState<string | null>(null);
  //: 此刻画布上挂着一块面板(产出者的,或剪一段的)—— 缩略图要让开,见 MiniMap。
  const composerShown = Boolean(trimming) || Boolean(!feeding.blocked && composerItem && producer && onRun);

  //: **关得掉。** 它是从操作条点开的一块面板,而面板一旦只有「成功剪完」这一条出路,
  //: 用户改主意时就被困住了。三条都给上:换选别的(或点空白处取消选中)、Esc、再点一次
  //: 那个按钮。此前一条都没有。
  React.useEffect(() => {
    if (!trimming) return;
    const still = nodes.some((node) => node.id === trimming && node.selected);
    if (!still) setTrimming(null);
  }, [trimming, nodes]);

  React.useEffect(() => {
    if (!trimming) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setTrimming(null);
    };
    return listenKeys(window, onKey);
  }, [trimming]);

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
      if (canAskWriter(item)) setWriterFor(item.id);
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
    [add, setEdges, setWriterFor],
  );

  /**
   * 从某一格长出一个工具格并连上:上游那一格就是它的输入(必填字段会默认接上它,见 ActionComposer)。
   * 摆放规则和其它种类同一个函数。
   */
  const spawnTool = React.useCallback(
    (producerId: string, from: string, at: { x: number; y: number }, fromIsSource = true) => {
      const { x, y } = ghostRect(at, toolCellSize(producers?.find((one) => one.id === producerId)), fromIsSource);
      const item = add("action", { x, y, form: { producer: producerId as BoardProducer } });
      setEdges((current) =>
        addEdge(
          fromIsSource
            ? { source: from, target: item.id, sourceHandle: null, targetHandle: null }
            : { source: item.id, target: from, sourceHandle: null, targetHandle: null },
          current,
        ),
      );
    },
    [add, setEdges, producers],
  );

  /**
   * 从节点拉出一条线、松手在空白处:摆一个占位、连一根待定的线、旁边挂单子
   * (见 components/app/canvasPendingLink)。选中一种就在占位那儿建真节点、连真线。
   *
   * 单子上除了几种格子,还有这个人能用的工具(把内容变成新内容的插件工具和内置节点),和工具条「添加」
   * 里同一份分组(boardTools:按它吃什么内容分 —— 处理图片、处理视频……),能搜。
   */
  const tools = React.useMemo(() => boardToolOptions(producers ?? []), [producers]);
  const linkChoices = React.useMemo(() => [...SPAWNABLE_KINDS, ...tools.map((one) => one.value)], [tools]);
  const describeChoice = React.useCallback(
    (choice: string) => {
      const tool = tools.find((one) => one.value === choice);
      if (tool) {
        return {
          icon: tool.icon,
          label: tool.label,
          hint: tool.description,
          group: tool.group,
          keywords: tool.keywords,
        };
      }
      const kind = choice as (typeof SPAWNABLE_KINDS)[number];
      return { icon: kindIcon(kind), ...kindText(t, kind), group: tools.length ? t("boardsGroupCreate") : undefined };
    },
    [t, tools],
  );
  const pending = usePendingLink({
    kinds: linkChoices,
    ghostSize: PENDING_GHOST_SIZE,
    describe: describeChoice,
    onChoose: (choice, link) =>
      isNodeProducer(choice)
        ? spawnTool(choice, link.nodeId, link.at, link.fromSource)
        : spawnLinked(choice as (typeof SPAWNABLE_KINDS)[number], link.nodeId, link.at, link.fromSource),
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

  /**
   * 从系统里拖文件进来 —— 传进素材库,再就地摆到落点上。
   *
   * 用仓库现成的 useFileDrop:整块区域拖放的三个坑(子元素边界上的 dragleave 抖动、
   * 浏览器默认打开文件、拖文字也亮提示)它已经处理过了,自己写要再踩一遍。
   *
   * **落点要在 drop 那一刻算**(那时才有鼠标位置),而 useFileDrop 的回调拿不到事件 ——
   * 和工作流那边一样,用一个 ref 把坐标从事件里带出来。
   */
  const dropAt = React.useRef<{ x: number; y: number } | null>(null);
  /** 文件进素材库,回来的每一份按种类各放一格(见 boardPlacement.assetItem)。拖进来和粘贴进来走这同一条。 */
  const importAndPlace = React.useCallback(
    (files: File[], at: { x: number; y: number }) => {
      void onDropFiles?.(files).then((assets) => {
        if (!assets?.length) return;
        setNodes((current) => [
          ...current.map((node) => ({ ...node, selected: false })),
          ...toNodes(assets.map((asset, index) => assetItem(asset, at, index))),
        ]);
      });
    },
    [onDropFiles, setNodes],
  );
  const drop = useFileDrop((files) => importAndPlace(files, dropAt.current ?? { x: 0, y: 0 }), isMediaFile);

  /**
   * 粘贴到画布上:截图 / 复制的媒体文件先进素材库再各放一格,一段文字落成一张便签,摆在视野中心。
   *
   * **冲着画布来的才接**(isCanvasKeyTarget):在便签里、提示词框里、任何输入框或编辑器里粘贴,是往那里
   * 贴字,不是往画布上放东西;经 Portal 弹出去的菜单、对话框也不算。评论 / 标记模式下不接。
   */
  React.useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      if (event.defaultPrevented || commentMode || markerMode) return;
      if (!isCanvasKeyTarget(event.target, surface.current)) return;
      const content = clipboardContent(event.clipboardData);
      if (!content) return;
      event.preventDefault();
      //: 便签走「添加」那一条(摆在视野中心、加完就选中);素材也摆在视野中心。
      if ("text" in content) {
        add("note", { text: content.text });
        return;
      }
      const instance = rf.current;
      const box = surface.current?.getBoundingClientRect();
      const center = instance && box
        ? instance.screenToFlowPosition({ x: box.left + box.width / 2, y: box.top + box.height / 2 })
        : { x: 0, y: 0 };
      importAndPlace(content.files, center);
    };
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, [add, importAndPlace, commentMode, markerMode]);

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
      onPointerDownCapture={(event) => {
        if (!commentMode || event.button !== 0) return;
        const target = event.target instanceof Element ? event.target : null;
        if (target?.closest("[data-suggestion-menu], [data-board-comment-mode-hint]")) return;
        const startedInsideOverlay = Boolean(target?.closest("[data-board-comment-overlay]"));
        const dismissedActive = Boolean(activeCommentId || draftAnchor);
        paneGesture.current = {
          x: event.clientX,
          y: event.clientY,
          moved: false,
          dismissedActive: startedInsideOverlay ? false : dismissedActive,
          startedInsideOverlay,
        };
        if (startedInsideOverlay) return;
        if (activeCommentId) onSelectComment?.(null);
        if (draftAnchor) setDraftAnchor(null);
      }}
      onPointerMoveCapture={(event) => {
        const gesture = paneGesture.current;
        if (!gesture) return;
        if (Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) > 5) gesture.moved = true;
      }}
      onPointerUpCapture={(event) => {
        const gesture = paneGesture.current;
        paneGesture.current = null;
        if (!gesture) return;
        const target = event.target instanceof Element ? event.target : null;
        const endedInsideOverlay = Boolean(target?.closest("[data-board-comment-overlay], [data-suggestion-menu]"));
        if (!shouldSuppressCommentPlacement({ ...gesture, endedInsideOverlay })) return;
        // pointerup is followed by click. Keep the guard through that click, then release it.
        suppressPaneClick.current = true;
        window.setTimeout(() => { suppressPaneClick.current = false; }, 0);
      }}
      onPointerCancelCapture={() => {
        paneGesture.current = null;
      }}
    >
      <MarkerEditorProvider enabled={markerMode && markersVisible}>
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
        onNodeDragStop={() => {
          carried.current = [];
          dragFrom.current = null;
        }}
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
        panOnScroll={inputMode === "trackpad"}
        zoomOnScroll={inputMode === "mouse"}
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
        {commentsVisible && (
          <ViewportPortal>
            {comments.map((comment, index) => {
              const preview = commentPositions[comment.id];
              const x = preview?.x ?? comment.anchor?.x;
              const y = preview?.y ?? comment.anchor?.y;
              if (typeof x !== "number" || typeof y !== "number") return null;
              const active = commentMode && activeCommentId === comment.id;
              const movable = commentMode && Boolean(onMoveComment) && canMoveComment(comment.author_id, currentUserId);
              return (
                <div
                  key={comment.id}
                  data-board-comment-overlay=""
                  className="nodrag nopan pointer-events-none absolute z-10 flex items-start gap-2"
                  style={{ left: x, top: y }}
                  onPointerDown={(event) => event.stopPropagation()}
                  onMouseDown={(event) => event.stopPropagation()}
                  onClick={(event) => event.stopPropagation()}
                  onDoubleClick={(event) => event.stopPropagation()}
                >
                  <button
                    type="button"
                    className={cn(
                      "grid h-7 w-7 touch-none -translate-x-1/2 -translate-y-1/2 shrink-0 place-items-center rounded-full border text-ui-2xs font-semibold shadow-[var(--shadow-panel)] transition-transform hover:scale-110",
                      movable && "cursor-grab active:cursor-grabbing",
                      active
                        ? "border-primary bg-action text-action-foreground"
                        : "border-floating-border bg-panel/90 text-foreground backdrop-blur-xl",
                    )}
                    tabIndex={commentMode ? 0 : -1}
                    style={{ pointerEvents: commentMode ? "auto" : "none" }}
                    title={comment.body}
                    aria-label={`${t("comments")} ${index + 1}`}
                    onPointerDown={(event) => {
                      event.stopPropagation();
                      if (!movable || event.button !== 0) return;
                      event.currentTarget.setPointerCapture(event.pointerId);
                      commentDrag.current = {
                        id: comment.id,
                        pointerId: event.pointerId,
                        startScreen: { x: event.clientX, y: event.clientY },
                        origin: { x, y },
                        nodeId: comment.anchor?.node_id ?? undefined,
                        moved: false,
                      };
                    }}
                    onPointerMove={(event) => {
                      const drag = commentDrag.current;
                      const instance = rf.current;
                      if (!drag || drag.id !== comment.id || drag.pointerId !== event.pointerId || !instance) return;
                      if (!drag.moved && Math.hypot(event.clientX - drag.startScreen.x, event.clientY - drag.startScreen.y) <= 4) return;
                      drag.moved = true;
                      const start = instance.screenToFlowPosition(drag.startScreen);
                      const current = instance.screenToFlowPosition({ x: event.clientX, y: event.clientY });
                      drag.last = {
                        x: drag.origin.x + current.x - start.x,
                        y: drag.origin.y + current.y - start.y,
                      };
                      const next = drag.last;
                      setCommentPositions((positions) => ({ ...positions, [comment.id]: next }));
                    }}
                    onPointerUp={(event) => {
                      const drag = commentDrag.current;
                      if (!drag || drag.id !== comment.id || drag.pointerId !== event.pointerId) return;
                      commentDrag.current = null;
                      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
                      if (!drag.moved || !drag.last) return;
                      suppressCommentClick.current = comment.id;
                      window.setTimeout(() => {
                        if (suppressCommentClick.current === comment.id) suppressCommentClick.current = null;
                      }, 0);
                      const anchor = { kind: "canvas" as const, ...drag.last, ...(drag.nodeId ? { node_id: drag.nodeId } : {}) };
                      void Promise.resolve(onMoveComment?.(comment, anchor))
                        .catch(() => undefined)
                        .finally(() => {
                          setCommentPositions((positions) => {
                            const next = { ...positions };
                            delete next[comment.id];
                            return next;
                          });
                        });
                    }}
                    onPointerCancel={(event) => {
                      const drag = commentDrag.current;
                      if (!drag || drag.id !== comment.id || drag.pointerId !== event.pointerId) return;
                      commentDrag.current = null;
                      setCommentPositions((positions) => {
                        const next = { ...positions };
                        delete next[comment.id];
                        return next;
                      });
                    }}
                    onClick={() => {
                      if (suppressCommentClick.current === comment.id) {
                        suppressCommentClick.current = null;
                        return;
                      }
                      onSelectComment?.(comment);
                    }}
                  >
                    {index + 1}
                  </button>
                  {active && (
                    <div className="-ml-3.5 -translate-y-3">
                      <CommentCard comment={comment} members={members} currentUserId={currentUserId}
                        onDelete={onDeleteComment ? () => onDeleteComment(comment) : undefined} />
                    </div>
                  )}
                </div>
              );
            })}
            {draftAnchor && typeof draftAnchor.x === "number" && typeof draftAnchor.y === "number" && (
              <div
                data-board-comment-overlay=""
                className="nodrag nopan pointer-events-none absolute z-20 flex items-start gap-2"
                style={{ left: draftAnchor.x, top: draftAnchor.y }}
                onPointerDown={(event) => event.stopPropagation()}
                onMouseDown={(event) => event.stopPropagation()}
                onClick={(event) => event.stopPropagation()}
                onDoubleClick={(event) => event.stopPropagation()}
              >
                <button
                  type="button"
                  data-comment-drag-handle=""
                  className="pointer-events-auto grid h-7 w-7 touch-none -translate-x-1/2 -translate-y-1/2 shrink-0 cursor-grab place-items-center rounded-full bg-action text-action-foreground shadow-[var(--shadow-panel)] active:cursor-grabbing"
                  aria-label={t("comments")}
                  onPointerDown={(event) => {
                    if (event.button !== 0) return;
                    event.preventDefault();
                    event.stopPropagation();
                    event.currentTarget.setPointerCapture(event.pointerId);
                    draftCommentDrag.current = {
                      pointerId: event.pointerId,
                      startScreen: { x: event.clientX, y: event.clientY },
                      origin: draftAnchor,
                      moved: false,
                    };
                  }}
                  onPointerMove={(event) => {
                    const drag = draftCommentDrag.current;
                    const instance = rf.current;
                    if (!drag || drag.pointerId !== event.pointerId || !instance) return;
                    if (!drag.moved && Math.hypot(event.clientX - drag.startScreen.x, event.clientY - drag.startScreen.y) <= 4) return;
                    drag.moved = true;
                    setDraftAnchor(moveCommentAnchorByScreenDelta(
                      drag.origin,
                      drag.startScreen,
                      { x: event.clientX, y: event.clientY },
                      (point) => instance.screenToFlowPosition(point),
                    ));
                  }}
                  onPointerUp={(event) => {
                    const drag = draftCommentDrag.current;
                    if (!drag || drag.pointerId !== event.pointerId) return;
                    draftCommentDrag.current = null;
                    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
                  }}
                  onPointerCancel={(event) => {
                    const drag = draftCommentDrag.current;
                    if (!drag || drag.pointerId !== event.pointerId) return;
                    draftCommentDrag.current = null;
                    setDraftAnchor(drag.origin);
                  }}
                >
                  <MessageSquare size={13} />
                </button>
                <div className="-ml-3.5 -translate-y-3">
                  <CommentComposer
                    members={members}
                    onCancel={() => setDraftAnchor(null)}
                    onSubmit={async (draft) => {
                      await onCreateComment?.(draftAnchor, draft);
                      setDraftAnchor(null);
                    }}
                  />
                </div>
              </div>
            )}
          </ViewportPortal>
        )}
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
          searchPlaceholder={tools.length ? t("boardToolSearch") : undefined}
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
        onSpawn={onRun ? spawnLinked : undefined}
        onTrimRequest={onRun ? (id) => setTrimming((current) => (current === id ? null : id)) : undefined}
        trimmingId={trimming}
        producers={producers}
        onAskWriter={onRun && !commentMode && !markerMode ? (id) => setWriterFor((current) => (current === id ? null : id)) : undefined}
        writerId={writerFor}
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
              }).finally(() => setTrimming(null));
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
        onFormChange: (form) => patch(composerItem.id, { form: withProducer(form, producer) }),
        onPickAsset,
        run: onRun,
        producers,
      })}
    </div>
  );
}

type GrowKind = (typeof SPAWNABLE_KINDS)[number];

/** 操作条上「接着做」的按钮按这个顺序排。 */
const GROW_ORDER: GrowKind[] = ["image", "video", "note", "audio"];

/**
 * 「接着做」:选中一格,能从它长出哪几种格子,悬停时各说什么。**一张表**,按(这一格的种类 → 长出的种类)查。
 *
 * 此前能长出哪几种是一串按种类的判断,悬停说明又另写一处,只分「便签 → 图片」和「其余 → 视频」两句 ——
 * 于是便签往下接视频时说「用这段文字生成图片」,文档往下接图片时说「用这张图当首帧生成视频」。
 * 便签、文档给的是文字:往下接图片、视频、音频(念出来)、文案;图片给首帧、视频给参考、音频给配乐:往下接视频;
 * 谁都能往下接一段文案。
 */
const GROW: Partial<Record<BoardItem["kind"], Partial<Record<GrowKind, MessageKey>>>> = {
  note: { image: "boardSpawnImageFromNote", video: "boardSpawnVideoFromText", note: "boardSpawnNote", audio: "boardSpawnAudio" },
  document: { image: "boardSpawnImageFromNote", video: "boardSpawnVideoFromText", note: "boardSpawnNote", audio: "boardSpawnAudio" },
  image: { video: "boardSpawnVideoFromImage", note: "boardSpawnNote" },
  video: { video: "boardSpawnVideoFromVideo", note: "boardSpawnNote" },
  audio: { video: "boardSpawnVideoFromAudio", note: "boardSpawnNote" },
  //: 3D 场景给的是它的预览图 —— 和一张图一样当首帧。
  scene: { video: "boardSpawnVideoFromImage", note: "boardSpawnNote" },
};

/** 这一格有没有东西可给:便签要有字,文档接上了就有,别的要有产出。空槽自己都还没有东西。 */
function hasContent(item: BoardItem): boolean {
  if (item.kind === "note") return Boolean(item.text?.trim());
  if (item.kind === "document") return true;
  return Boolean(item.asset_id);
}

/**
 * 选中一项时浮在它上面的操作条。
 *
 * **按类型给动作,不给一套通用的**:便签要换颜色,图片/视频要换素材,分组框两者都不要。
 * 摆一排一半是灰的按钮,等于让用户每次都先分辨哪些能点。
 *
 * 位置跟着选中项走 —— 用 NodeToolbar,它渲染在 React Flow 的视口层里,平移缩放时自己跟着动
 * (工作流那边的检查器用的是同一个原语)。
 */
function ItemToolbar({
  nodes,
  setNodes,
  onRemoveSelected,
  onCopySelected,
  onRename,
  onPickAsset,
  onSpawn,
  onTrimRequest,
  trimmingId,
  producers,
  onAskWriter,
  writerId,
}: {
  nodes: Node[];
  setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
  /** 删掉选中的这几项 —— **连同挂在它们上面的线**。见 Inner 里的实现。 */
  onRemoveSelected: () => void;
  /** 复制选中的这几项(见 copySelected)。 */
  onCopySelected: () => void;
  /** 给这一格改名:打开它上方名字那一处的输入框(和双击名字是同一个状态)。 */
  onRename?: (itemId: string) => void;
  onPickAsset: Props["onPickAsset"];
  /** 从这一项长出下一项并连上。没给 = 这张画板不支持生成(上层没接生成能力)。 */
  onSpawn?: (
    kind: (typeof SPAWNABLE_KINDS)[number],
    from: string,
    at: { x: number; y: number },
    fromIsSource?: boolean,
  ) => void;
  /** 请求给这一项定剪辑范围(再点一次收起)。没给 = 这张画板不支持剪辑。 */
  onTrimRequest?: (itemId: string) => void;
  /** 当前开着剪辑面板的那一项 —— 按钮据此变成按下态,再点一次就收起。 */
  trimmingId?: string | null;
  /** 产出者清单:空槽能在哪几个之间切(音频槽:配音 / 生成)。 */
  producers?: BoardProducerInfo[];
  /** 打开 / 收起这张便签的「让 AI 写」面板。没给 = 这张画板不支持写(上层没接产出者)。 */
  onAskWriter?: (itemId: string) => void;
  /** 当前开着写作面板的那一张 —— 按钮据此变成按下态,再点一次就收起。 */
  writerId?: string | null;
  /** 把当前选中的这几项圈成一组。 */
}) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  // 标记不进这条操作条:它没有素材、不生成、不换一份,而这里每个动作都要读它没有的 item
  // (「复制一份」此前就会在这里抛)。它自己的改名/绑键/删除开在旗子上。
  const selected = nodes.filter((node) => node.selected && node.type !== "marker");
  // 多选时只给共通的动作 —— 逐个类型的动作在混选下没有一致的含义。
  const single = selected.length === 1 ? selected[0] : null;
  //: 操作条和面板一样,格子贴着画布边时不钻到侧栏底下(横向平移回来;它只有一行,不收高度)。
  const bar = React.useRef<HTMLDivElement | null>(null);
  const fit = useKeepInCanvas(bar, { vertical: false });
  if (selected.length === 0) return null;

  const item = single ? (single.data as unknown as { item: BoardItem }).item : null;

  const patch = (id: string, next: Partial<BoardItem>) =>
    setNodes((current) =>
      current.map((node) =>
        node.id === id
          ? { ...node, data: { ...node.data, item: { ...(node.data as { item: BoardItem }).item, ...next } } }
          : node,
      ),
    );

  const duplicate = onCopySelected;

  return (
    //: 上下浮层都从**节点边框**量同一段距离。类型标签挂在节点外,但不能因此让上方浮层
    //: 另用一套数字 —— 否则一眼看过去就是上疏下密。
    <NodeToolbar nodeId={selected.map((node) => node.id)} isVisible position={Position.Top} offset={BOARD_NODE_PANEL_OFFSET}>
      <div
        ref={bar}
        style={fit}
        className="nodrag nopan flex items-center gap-1 whitespace-nowrap rounded-full border border-floating-border bg-panel p-1.5 shadow-[var(--shadow-panel)]"
      >
        {/* 按类型来的那几个动作装在这一格里,**分隔线是这一格自己的右边框**。
            于是它不可能在没有动作时出现 —— 此前那道线自己抄了一遍「上面有没有东西」的
            条件,加了音频节点之后就和实际渲染分了岔:音频头上挂着一道悬空的竖线。 */}
        <div className="flex items-center gap-1 empty:hidden [&:not(:empty)]:mr-1 [&:not(:empty)]:border-r [&:not(:empty)]:border-border [&:not(:empty)]:pr-2">
        {item?.kind === "note" &&
          NOTE_COLORS.map((color) => (
            <button
              key={color}
              type="button"
              aria-label={color}
              className={cn(
                "h-6 w-6 cursor-pointer rounded-full border transition-transform hover:scale-110",
                noteColorClass(color),
                item.color === color && "ring-2 ring-primary ring-offset-1 ring-offset-[var(--panel)]",
              )}
              onClick={() => patch(item.id, { color })}
            />
          ))}

        {/* 让 AI 写:**明确的一个动作**,不是选中的副作用(见 Inner 的 writerFor)。工具交回的结构化数据
            (JSON 便签)不给 —— 那是一份数据,不是一段要改写的文案。 */}
        {single && item && onAskWriter && canAskWriter(item) && (
          <button
            type="button"
            aria-pressed={writerId === item.id}
            title={t("boardAskAiWriteTitle")}
            className={cn(
              "flex cursor-pointer items-center gap-1.5 shrink-0 whitespace-nowrap rounded-full px-2.5 py-1.5 text-ui-xs transition-colors hover:bg-secondary hover:text-foreground",
              writerId === item.id ? "bg-secondary text-foreground" : "text-muted-foreground",
            )}
            onClick={() => onAskWriter(item.id)}
          >
            <Sparkles size={13} /> {t("boardAskAiWrite")}
          </button>
        )}

        {/* 分组框:**这一组是不是一个整体**。开着的时候拖框会把框里的东西一起带走 ——
            没有它的话,想把一组想法整体挪个位置就得一个个拖。 */}
        {item?.kind === "frame" && (
          <button
            type="button"
            aria-pressed={Boolean(item.move_children)}
            title={t(item.move_children ? "boardMoveChildrenOn" : "boardMoveChildrenOff")}
            className={cn(
              "flex cursor-pointer items-center gap-1.5 shrink-0 whitespace-nowrap rounded-full px-2.5 py-1.5 text-ui-xs transition-colors",
              item.move_children
                ? "bg-primary/12 text-primary"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
            onClick={() => patch(item.id, { move_children: !item.move_children })}
          >
            <Group size={13} /> {t("boardMoveChildren")}
          </button>
        )}

        {/* 预览:**看大图是一个明确的动作,不是点在图上的副作用**。画布上点一下的意思是
            选中这个节点 —— 让图片自己接管点击的话,操作条和表单都弹不出来。 */}
        {(item?.kind === "image" || item?.kind === "video") && item.asset_id && (
          <button
            type="button"
            className="flex cursor-pointer items-center gap-1.5 shrink-0 whitespace-nowrap rounded-full px-2.5 py-1.5 text-ui-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
            title={t("boardPreviewTitle")}
            onClick={() =>
              openImagePreview({
                src: item.kind === "image"
                  ? assetPreviewUrl(item.asset_id as string)
                  : assetFileUrl(item.asset_id as string),
                title: item.title || item.text || "",
                //: 视频走同一个灯箱,只是那一项渲染成播放器 —— 见 image-preview。
                video: item.kind === "video",
              })
            }
          >
            <Maximize2 size={13} /> {t("boardPreview")}
          </button>
        )}

        {/* 剪一段:视听素材才有时间轴,一张图截不出「第 3 秒」。 */}
        {onTrimRequest && item?.asset_id && (item.kind === "video" || item.kind === "audio") && (
          <button
            type="button"
            className={cn(
              "flex cursor-pointer items-center gap-1.5 shrink-0 whitespace-nowrap rounded-full px-2.5 py-1.5 text-ui-xs transition-colors hover:bg-secondary hover:text-foreground",
              trimmingId === item.id ? "bg-secondary text-foreground" : "text-muted-foreground",
            )}
            title={t("boardTrimTitle")}
            onClick={() => onTrimRequest(item.id)}
            aria-pressed={trimmingId === item.id}
          >
            <Scissors size={13} /> {t("boardTrim")}
          </button>
        )}

        {item && isMediaKind(item.kind) && (
          <button
            type="button"
            className="flex cursor-pointer items-center gap-1.5 shrink-0 whitespace-nowrap rounded-full px-2.5 py-1.5 text-ui-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
            onClick={() =>
              onPickAsset(item.kind as MediaKind, (assetId) =>
                // 手动换素材不是上一轮 AI 任务的“成功产物”。把运行态归回 idle，同时 asset_id
                // 变化会让对应 Composer 从节点表单重新水合，清掉上一轮局部 touched/submitting。
                patch(item.id, { asset_id: assetId, run: { status: "idle" } }),
              )
            }
          >
            <Replace size={13} /> {t("boardReplaceAsset")}
          </button>
        )}

        {/* 从这一项长出下一项:**放一个空节点并连上,不是直接开跑**。
            空节点一选中它的表单就开着,提示词已经由上游这一项填好(便签给文字、图片给首帧),
            用户还能改模型、改比例、再挂张参考图 —— 点一下就把任务发出去的话,这些他一个都
            来不及说。已经在生成的那一项不给(它还没有产出)。 */}
        {/* 空槽用什么产出:一种格子有几个能填空槽的产出者时(音频槽:配音 / 生成音乐音效)给一个切换。
            **只换表单上写的那个产出者**,面板随之换成它的;在跑的时候不给换。 */}
        {single && item && !itemIsRunning(item) && slotProducers(item, producers).length > 0 && (
          <div role="radiogroup" aria-label={t("boardProducerSwitch")} className="flex items-center gap-0.5 rounded-full bg-secondary/60 p-0.5">
            {slotProducers(item, producers).map((one) => {
              const on = item.form?.producer === one.id;
              return (
                <button
                  key={one.id}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  title={toPlainText(one.description)}
                  className={cn(
                    "cursor-pointer rounded-full px-2.5 py-1 text-ui-xs transition-colors",
                    on ? "bg-panel text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                  )}
                  onClick={() => patch(item.id, { form: { ...item.form, producer: one.id as BoardProducer } })}
                >
                  {one.label}
                </button>
              );
            })}
          </div>
        )}

        {/* 从这一项长出下一项:**放一个空节点并连上,不是直接开跑**。空节点一选中它的面板就开着,
            用户还能改模型、改比例、再挂张参考图 —— 点一下就把任务发出去的话,这些他一个都来不及说。
            长出哪几种、每一个悬停时说什么,是同一张表(GROW);图标是要长出来的那种格子的图标,
            一眼看出这一下会多出一张图、一段视频还是一张便签。已经在跑的那一项不给(它还没有产出)。 */}
        {/* 「生成」这一组:前面一个淡淡的「生成」,后面每一枚只写要长出来的那种东西(图片、视频、文案、音频)——
            此前四枚都写「生成图片」「生成视频」…,一条操作条排不下,字被折成两行。完整的一句在悬停里。 */}
        {onSpawn && single && item && !itemIsRunning(item) && hasContent(item) && GROW_ORDER.some((kind) => GROW[item.kind]?.[kind]) && (
          <span aria-hidden className="shrink-0 pl-1 text-ui-2xs text-muted-foreground/70">{t("boardGrowLabel")}</span>
        )}
        {onSpawn && single && item && !itemIsRunning(item) && hasContent(item) &&
          GROW_ORDER.filter((kind) => GROW[item.kind]?.[kind]).map((kind) => {
            const Icon = kindIcon(kind);
            return (
              <button
                key={kind}
                type="button"
                data-board-grow={kind}
                className="flex cursor-pointer items-center gap-1.5 shrink-0 whitespace-nowrap rounded-full px-2.5 py-1.5 text-ui-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
                title={t(GROW[item.kind]?.[kind] as MessageKey)}
                onClick={() =>
                  onSpawn(kind, item.id, {
                    x: single.position.x + (single.width ?? 260) + 60,
                    y: single.position.y + (single.height ?? 180) / 2,
                  })
                }
              >
                <Icon size={13} />{" "}
                {/* 文案那一格说的是「生成文案」而不是「生成便签」—— 便签是这张卡片的名字,
                    而用户要的是里面那段字。套同一个模板会说出「Generate Note」这种话。 */}
                {kind === "note" ? t("boardGrowCopy") : kindText(t, kind).label}
              </button>
            );
          })}
        </div>

        {/* 改名只对一格有意义 —— 多选时一起改成同一个名字,等于让它们重新分不清。 */}
        {single && item && onRename && (
          <button
            type="button"
            aria-label={t("rename")}
            title={t("rename")}
            className="grid h-7 w-7 cursor-pointer place-items-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground"
            onClick={() => onRename(item.id)}
          >
            <PencilLine size={13} />
          </button>
        )}
        <button
          type="button"
          aria-label={t("copy")}
          title={t("copy")}
          className="grid h-7 w-7 cursor-pointer place-items-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground"
          onClick={duplicate}
        >
          <Copy size={13} />
        </button>
        <button
          type="button"
          aria-label={t("delete")}
          title={t("delete")}
          className="grid h-7 w-7 cursor-pointer place-items-center rounded-full text-muted-foreground hover:text-destructive"
          onClick={onRemoveSelected}
        >
          <Trash2 size={13} />
        </button>
      </div>
    </NodeToolbar>
  );
}

export function BoardCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <Inner {...props} />
    </ReactFlowProvider>
  );
}
