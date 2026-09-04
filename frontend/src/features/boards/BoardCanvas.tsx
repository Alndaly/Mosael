import React from "react";
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
  type Connection,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from "@xyflow/react";
import { Copy, FileUp, Group, Loader2, Maximize2, MessageSquare, Replace, Scissors, Sparkles, Trash2 } from "lucide-react";

import { assetFileUrl, assetPreviewUrl, type CollaborationComment, type WorkspaceMember } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { useImagePreview } from "@/components/app/image-preview";
import { fitCanvasViewport } from "@/components/app/fitCanvasViewport";

import type { BoardCanvas as Canvas, BoardItem, GenerationOption } from "@/api/client";
import { NodeComposer } from "@/features/boards/NodeComposer";
import { isMediaFile, useFileDrop } from "@/lib/useFileDrop";
import { usePersistentViewport } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";
import { canRedo, canUndo, emptyHistory, record, redo, undo } from "@/features/boards/canvasHistory";
import { AudioComposer } from "@/features/boards/AudioComposer";
import { TrimComposer } from "@/features/boards/TrimComposer";
import { NoteComposer } from "@/features/boards/NoteComposer";
import { BOARD_NODE_TYPES, DEFAULT_SIZE, NOTE_COLORS, noteColorClass , isMediaKind, kindIcon, kindText, SPAWNABLE_KINDS, type MediaKind } from "@/features/boards/boardNodes";
import { itemFormResetKey, itemIsRunning } from "@/features/boards/boardItemState";
import { BOARD_NODE_PANEL_OFFSET } from "@/features/boards/boardLayout";
import { BoardCommentComposer, type CommentDraft } from "@/features/boards/BoardCommentComposer";

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

/** 只放**数据**。回调在渲染时注入(见 displayNodes)—— 存进节点里的话,它们会闭包住
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
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}

function toNodes(items: BoardItem[]): Node[] {
  return items.map((item) => ({
    id: item.id,
    type: item.kind,
    position: { x: item.x, y: item.y },
    width: item.width ?? DEFAULT_SIZE[item.kind].width,
    height: item.height ?? DEFAULT_SIZE[item.kind].height,
    data: { item },
    // 分组框永远在最底 —— 它是背景,盖住上面的项就没法点了。
    zIndex: item.kind === "frame" ? 0 : 1,
  }));
}

/** 把 React Flow 的当前状态汇成要存的画布。**位置以 React Flow 为准** —— 它才是刚被拖过的那份。 */
export function toCanvas(nodes: Node[], edges: Edge[]): Canvas {
  return {
    items: nodes.map((node) => {
      const { item } = node.data as unknown as { item: BoardItem };
      return {
        ...item,
        x: Math.round(node.position.x),
        y: Math.round(node.position.y),
        width: Math.round(node.width ?? node.measured?.width ?? DEFAULT_SIZE[item.kind].width),
        height: Math.round(node.height ?? node.measured?.height ?? DEFAULT_SIZE[item.kind].height),
      };
    }),
    edges: edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })),
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

export function canMoveComment(authorId: string | null, currentUserId: string | null | undefined): boolean {
  return Boolean(authorId && currentUserId && authorId === currentUserId);
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

interface Props {
  boardId: string;
  /** 提示词面板里 `@` 引用素材时去哪个工作区找。 */
  workspaceId: string;
  canvas: Canvas;
  onChange: (canvas: Canvas) => void;
  /** 让上层开素材选择器。kind 决定它列图片还是视频 —— 选得到的就该是贴上去能看的。 */
  onPickAsset: (kind: MediaKind, place: (assetId: string) => void) => void;
  /** 从某一项生成。上层拿得到 workspaceId 和接口,画布只提供"放哪儿"和"填回来"。 */
  onGenerate?: (input: {
    kind: "image" | "video";
    prompt: string;
    /** 填进**这一格**(节点即生成单元)。不给就是另开一格放在源节点右边。 */
    itemId?: string;
    x?: number;
    y?: number;
    provider?: string;
    model?: string;
    parameters?: Record<string, unknown>;
    sourceAssets?: { asset_id: string; role: string }[];
    form?: BoardItem["form"];
  }) => Promise<unknown>;
  /** 让 AI 往某张便签里写字。**同步** —— 写字几秒就回,不走生成任务那条路。 */
  /** 把一段文字念成音频。**异步** —— 走和出图出片同一套占位/回执。 */
  onSpeak?: (input: { itemId: string; text: string; voiceId: string }) => Promise<unknown>;
  /** 取某一帧,存成一份新素材、落到一个新节点上 —— 原素材不动。 */
  onGrabFrame?: (input: { assetId: string; at: number; x: number; y: number }) => Promise<unknown>;
  /** 截出一段。产出是一份**新素材**,落到一个新节点上 —— 原素材不动。 */
  onTrim?: (input: {
    itemId: string;
    assetId: string;
    start: number;
    end: number;
    mute: boolean;
    x: number;
    y: number;
  }) => Promise<unknown>;
  onWrite?: (input: {
    itemId: string;
    prompt: string;
    providerProfileId: string;
    model: string;
    /** 让模型看着写的图片(上游连过来的 + 正文里 @ 到的)。 */
    assets: string[];
    /** 上游便签给的材料。 */
    context: string[];
  }) => Promise<unknown>;
  /** 可用的生成模型 —— 提示词面板要让人选。 */
  models?: GenerationOption[];
  /** 全览开着没有。占右下角一块不小的地方,图小的时候纯属挡视线。 */
  showMinimap?: boolean;
  /** 系统里拖进来的文件:上层负责传进素材库,回来的每一份就地摆到落点上。 */
  onDropFiles?: (files: File[]) => Promise<{ id: string; name: string; kind: "image" | "video" }[]>;
  uploading?: boolean;
  /** Pixels covered by a docked panel on the right; excluded from fit-to-content. */
  rightOverlayWidth?: number;
  /** Comment mode is separate: a canvas or node click anchors a discussion instead of editing nodes. */
  commentMode?: boolean;
  comments?: CollaborationComment[];
  members?: WorkspaceMember[];
  currentUserId?: string | null;
  activeCommentId?: string | null;
  onSelectComment?: (comment: CollaborationComment | null) => void;
  onCreateComment?: (anchor: NonNullable<CollaborationComment["anchor"]>, draft: CommentDraft) => Promise<unknown>;
  onMoveComment?: (comment: CollaborationComment, anchor: NonNullable<CollaborationComment["anchor"]>) => Promise<unknown>;
  onDeleteComment?: (comment: CollaborationComment) => Promise<unknown>;
  onExitCommentMode?: () => void;
  /** 把「加一项」交给上层 —— 顶栏那两组胶囊要摆在一起(和工作流详情页一致),
   *  而 add 依赖画布内部的 rf 实例和 setNodes,只能由画布提供。 */
  onReady?: (api: BoardCanvasApi) => void;
}

function Inner({ boardId, workspaceId, canvas, onChange, onPickAsset, onGenerate, onWrite, onSpeak, onTrim, onGrabFrame, models, showMinimap = true, onDropFiles, uploading, rightOverlayWidth = 0, commentMode = false, comments = [], members = [], currentUserId, activeCommentId, onSelectComment, onCreateComment, onMoveComment, onDeleteComment, onExitCommentMode, onReady }: Props) {
  const t = useI18n();
  const rf = React.useRef<ReactFlowInstance | null>(null);
  const surface = React.useRef<HTMLDivElement | null>(null);
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
  const suppressCommentClick = React.useRef<string | null>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState(toNodes(canvas.items));
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(
    canvas.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })),
  );

  React.useEffect(() => {
    if (!commentMode) setDraftAnchor(null);
    else setNodes((current) => current.map((node) => (node.selected ? { ...node, selected: false } : node)));
  }, [commentMode, setNodes]);

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
  const composerItem = React.useMemo(() => {
    const picked = nodes.filter((node) => node.selected);
    if (picked.length !== 1) return null;
    const item = (picked[0].data as unknown as { item: BoardItem }).item;
    if (item.kind === "image" || item.kind === "video" || item.kind === "audio") {
      return item.asset_id ? null : item;
    }
    //: **便签不论空不空都挂。** 空的是「从头写」,有字的是「照我说的改」—— 后者才是这块
    //: 面板最常被用到的样子(写完之后想「短一半」「换个语气」)。双击进编辑照旧,两者不冲突:
    //: 面板挂在节点下方,不盖着字。
    if (item.kind === "note") return item;
    return null;
  }, [nodes]);

  /**
   * 连到这个节点上的上游产出,按连线的先后。
   *
   * **这就是那条线的意思。** 连了线还要再挂一遍素材的话,线就只是根装饰;所以这里把上游
   * 已经出了产出的项收上来,交给面板照当前生成方式挂进槽位(一张图当首帧、多张当参考)。
   * 还没出产出的上游跳过 —— 它自己都还没有东西可给。
   */
  const feeding = React.useMemo(() => {
    if (!composerItem) return { assets: [], texts: [] as { itemId: string; text: string }[] };
    const byId = new Map(
      nodes.map((node) => [node.id, (node.data as unknown as { item: BoardItem }).item]),
    );
    const sources = edges
      .filter((edge) => edge.target === composerItem.id)
      .map((edge) => byId.get(edge.source))
      .filter((item): item is BoardItem => Boolean(item));
    return {
      assets: sources
        .filter((item) => item.asset_id)
        .map((item) => ({ assetId: item.asset_id as string, kind: item.kind })),
      //: **便签给的是提示词,不是素材。** 一张写着描述的便签连到图片上,用户的意思是
      //: 「照这段话画」—— 而不是把便签当参考图(它根本没有图)。
      texts: sources
        .filter((item) => item.kind === "note" && (item.text ?? "").trim())
        .map((item) => ({ itemId: item.id, text: (item.text ?? "").trim() })),
    };
  }, [composerItem, edges, nodes]);

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
      const item = (node.data as unknown as { item: BoardItem }).item;
      carried.current = [];
      dragFrom.current = null;
      if (item.kind !== "frame" || !item.move_children) return;
      const left = node.position.x;
      const top = node.position.y;
      const right = left + (node.width ?? DEFAULT_SIZE.frame.width);
      const bottom = top + (node.height ?? DEFAULT_SIZE.frame.height);
      dragFrom.current = { ...node.position };
      carried.current = nodes
        .filter((one) => one.id !== node.id && one.type !== "frame")
        //: 按**中心**判在不在框里,不是按有没有碰到 —— 压着边线的那一项,用碰撞判会
        //: 跟着走,而它看起来明明在框外。
        .filter((one) => {
          const cx = one.position.x + (one.width ?? 0) / 2;
          const cy = one.position.y + (one.height ?? 0) / 2;
          return cx >= left && cx <= right && cy >= top && cy <= bottom;
        })
        .map((one) => ({ id: one.id, from: { ...one.position } }));
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

  //: 渲染用的节点 = 数据 + 这一轮的回调。**每轮重新贴** —— 回调闭包着最新的 setNodes,
  //: 而把它们存进节点数据会让节点的初值反过来依赖 setNodes,那个循环绕不开。
  const displayNodes = React.useMemo(
    () => nodes.map((node) => ({
      ...node,
      data: { ...node.data, onText: setText, onAspect: setAspect, commentMode },
    })),
    [nodes, setText, setAspect, commentMode],
  );

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

  const restore = React.useCallback(
    (snapshot: string) => {
      const canvas = JSON.parse(snapshot) as Canvas;
      restoring.current = snapshot;
      setNodes(toNodes(canvas.items));
      setEdges(canvas.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })));
    },
    [setNodes, setEdges],
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
      const picked = current.filter((node) => node.selected);
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
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [stepBack, stepForward, groupSelection]);

  const add = React.useCallback(
    (kind: BoardItem["kind"], extra: Partial<BoardItem> = {}) => {
      const instance = rf.current;
      // 放在**视野中心**,不是原点:画板可以拖得很远,放原点等于放到看不见的地方。
      const center = instance
        ? instance.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 })
        : { x: 0, y: 0 };
      const item: BoardItem = {
        id: `${kind}-${Date.now().toString(36)}`,
        kind,
        x: Math.round(center.x - DEFAULT_SIZE[kind].width / 2),
        y: Math.round(center.y - DEFAULT_SIZE[kind].height / 2),
        ...DEFAULT_SIZE[kind],
        ...(kind === "note" ? { color: "yellow" } : {}),
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
  //: 正在给哪一项定剪辑范围。**不是选中就弹** —— 「剪一段」是对已有产出的动作,
  //: 而选中一段片子最常见的意图是看它、拖它,不是剪它。
  const [trimming, setTrimming] = React.useState<string | null>(null);

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
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [trimming]);

  //: 哪一张便签正在写。写字是同步的几秒,期间按钮转圈 —— 不给反馈的话用户会再点一次。
  const [writing, setWriting] = React.useState<string | null>(null);

  const [linkMenu, setLinkMenu] = React.useState<
    {
      screenX: number;
      screenY: number;
      /** 那条线的起点(屏幕坐标)—— 松手后 React Flow 会把它正在拖的线撤掉,
       *  而菜单还开着:没有这段线,看起来就像刚拉的那条线没了。 */
      fromX: number;
      fromY: number;
      x: number;
      y: number;
      from: string;
      fromIsSource: boolean;
    } | null
  >(null);

  /**
   * 从某一项长出下一项,并连上。
   *
   * 「从这张便签生成图片」「从这张图生成视频」走的都是它:**放一个空节点、连上线,而不是
   * 直接开跑**。空节点一选中,它的表单就打开了,提示词也已经由上游那张便签填好 —— 用户
   * 还能改模型、改比例、再挂张参考图。点一下就把任务发出去的话,这些他一个都来不及说。
   */
  const spawnLinked = React.useCallback(
    (kind: (typeof SPAWNABLE_KINDS)[number], from: string, at: { x: number; y: number }, fromIsSource = true) => {
      const size = DEFAULT_SIZE[kind];
      const item = add(kind, {
        x: Math.round(at.x - (fromIsSource ? 0 : size.width)),
        y: Math.round(at.y - size.height / 2),
      });
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
  const drop = useFileDrop((files) => {
    const at = dropAt.current ?? { x: 0, y: 0 };
    void onDropFiles?.(files).then((assets) => {
      if (!assets?.length) return;
      setNodes((current) => [
        ...current.map((node) => ({ ...node, selected: false })),
        ...assets.flatMap((asset, index) =>
          toNodes(
            [
              {
                id: `${asset.kind}-${Math.random().toString(36).slice(2, 9)}`,
                kind: asset.kind,
                // 多个文件斜着摞开,不然它们会精确重叠成一个。
                x: Math.round(at.x + index * 24),
                y: Math.round(at.y + index * 24),
                ...DEFAULT_SIZE[asset.kind],
                asset_id: asset.id,
                text: asset.name,
              },
            ],
          ),
        ),
      ]);
    });
  }, isMediaFile);

  React.useEffect(() => {
    onReady?.({
      add,
      patch,
      replace: (next) => restore(JSON.stringify(next)),
      fitView: () => {
        if (rf.current && surface.current) {
          void fitCanvasViewport(rf.current, surface.current, { right: rightOverlayWidth });
        }
      },
      focusComment: (comment) => {
        const x = comment.anchor?.x;
        const y = comment.anchor?.y;
        if (rf.current && typeof x === "number" && typeof y === "number") {
          void rf.current.setCenter(x, y, { zoom: Math.max(rf.current.getZoom(), 0.9), duration: 350 });
        }
      },
      undo: stepBack,
      redo: stepForward,
      canUndo: canUndo(history),
      canRedo: canRedo(history),
    });
  }, [add, patch, onReady, rightOverlayWidth, stepBack, stepForward, history, restore]);

  return (
    // 详情页本身就是画布边界:四边满铺,不再套第二层卡片边框或圆角。
    <div
      ref={surface}
      className="relative h-full w-full overflow-hidden bg-background"
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
        if (target?.closest("[data-suggestion-menu]")) return;
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
      <ReactFlow
        nodes={displayNodes}
        edges={edges}
        nodeTypes={BOARD_NODE_TYPES}
        minZoom={0.1}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(event, node) => {
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
          if (!canPlaceCommentDraft(commentMode, Boolean(draftAnchor), suppressPaneClick.current) || !rf.current) return;
          const point = rf.current.screenToFlowPosition({ x: event.clientX, y: event.clientY });
          setDraftAnchor({ kind: "canvas", x: point.x, y: point.y });
        }}
        onConnect={(connection: Connection) => {
          if (commentMode) return;
          setEdges((current) => addEdge(connection, current));
        }}
        // 可见的 + 在边界外，而真实锚点贴在边界上。扩大屏幕命中半径后，拖到 + 上即可
        // 自动吸附，不必再精确瞄准那个透明的 8px handle。
        connectionRadius={32}
        //: 线拉到空白处松手 —— 用户已经想好了「从这儿接下去」,弹一张单子让他直接选。
        //: 连到别的节点上时 isValid 为真,那是正常连线,不该弹。
        onConnectEnd={(event, connection) => {
          if (commentMode) return;
          const instance = rf.current;
          const from = connection.fromNode?.id;
          if (connection.isValid || !instance || !from) return;
          const point = "changedTouches" in event ? event.changedTouches[0] : (event as MouseEvent);
          if (!point) return;
          const flow = instance.screenToFlowPosition({ x: point.clientX, y: point.clientY });
          //: 起点取那个 handle 自己的位置 —— 菜单开着的这段时间要把线接上,
          //: 否则用户看到的是「我拉的线松手就没了」。
          const handle = document
            .querySelector(`.react-flow__node[data-id="${CSS.escape(from)}"]`)
            ?.querySelector(
              connection.fromHandle?.type === "target"
                ? ".react-flow__handle-left"
                : ".react-flow__handle-right",
            )
            ?.getBoundingClientRect();
          setLinkMenu({
            screenX: point.clientX,
            screenY: point.clientY,
            fromX: handle ? handle.x + handle.width / 2 : point.clientX,
            fromY: handle ? handle.y + handle.height / 2 : point.clientY,
            x: flow.x,
            y: flow.y,
            from,
            fromIsSource: connection.fromHandle?.type !== "target",
          });
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
              void fitCanvasViewport(instance, surface.current, { right: rightOverlayWidth }, { maxZoom: 1 });
            }
            setReady(true);
          });
        }}
        onMoveEnd={(_event, next) => viewport.remember(next)}
        // 双击空白处直接加一张便签 —— 想法来的时候不该先去找按钮。
        onDoubleClick={(event) => {
          if (commentMode) return;
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
          };
          setNodes((current) => [...current, ...toNodes([item])]);
        }}
        className={cn(!ready && "opacity-0", commentMode && "cursor-crosshair")}
        proOptions={{ hideAttribution: false }}
        /* 触控板约定(Figma / Miro 那套):双指滑动 = 平移,捏合 = 缩放。**和工作流画布同一套** ——
           React Flow 默认 zoomOnScroll:true,而 macOS 触控板双指滑动发出的正是 wheel 事件,
           于是「想拖画布」变成了「缩放」。捏合发的是 ctrlKey 的 wheel,归 zoomOnPinch 管,
           所以关掉 zoomOnScroll 不影响捏合;鼠标用户按住 ctrl/⌘ 滚轮同样落进这条,仍可缩放。 */
        panOnScroll
        zoomOnScroll={false}
        zoomOnPinch
        maxZoom={2.5}
        deleteKeyCode={["Backspace", "Delete"]}
        nodesDraggable={!commentMode}
        nodesConnectable={!commentMode}
        elementsSelectable={!commentMode}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} />
        {commentMode && (
          <ViewportPortal>
            {comments.map((comment, index) => {
              const preview = commentPositions[comment.id];
              const x = preview?.x ?? comment.anchor?.x;
              const y = preview?.y ?? comment.anchor?.y;
              if (typeof x !== "number" || typeof y !== "number") return null;
              const active = activeCommentId === comment.id;
              const movable = Boolean(onMoveComment) && canMoveComment(comment.author_id, currentUserId);
              const deletable = Boolean(onDeleteComment) && canMoveComment(comment.author_id, currentUserId);
              return (
                <div
                  key={comment.id}
                  data-board-comment-overlay=""
                  className="nodrag nopan pointer-events-auto absolute z-10 flex items-start gap-2"
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
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border-strong bg-panel/90 text-foreground backdrop-blur-xl",
                    )}
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
                        nodeId: comment.anchor?.node_id,
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
                    <div className="-ml-3.5 -translate-y-3 w-64 rounded-xl border border-border-strong bg-panel/95 p-3 text-left shadow-[var(--shadow-panel)] backdrop-blur-xl">
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <p className="min-w-0 truncate text-ui-xs font-semibold text-foreground">
                          {comment.author?.display_name || comment.author?.username || t("teamSystemActor")}
                        </p>
                        {deletable && (
                          <button
                            type="button"
                            data-delete-comment=""
                            className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                            title={t("delete")}
                            aria-label={t("delete")}
                            onClick={() => {
                              void Promise.resolve(onDeleteComment?.(comment)).catch(() => undefined);
                            }}
                          >
                            <Trash2 size={12} />
                          </button>
                        )}
                      </div>
                      <p className="whitespace-pre-wrap text-ui-sm leading-relaxed text-foreground">{comment.body}</p>
                    </div>
                  )}
                </div>
              );
            })}
            {draftAnchor && typeof draftAnchor.x === "number" && typeof draftAnchor.y === "number" && (
              <div
                data-board-comment-overlay=""
                className="nodrag nopan pointer-events-auto absolute z-20 flex items-start gap-2"
                style={{ left: draftAnchor.x, top: draftAnchor.y }}
                onPointerDown={(event) => event.stopPropagation()}
                onMouseDown={(event) => event.stopPropagation()}
                onClick={(event) => event.stopPropagation()}
                onDoubleClick={(event) => event.stopPropagation()}
              >
                <span className="grid h-7 w-7 -translate-x-1/2 -translate-y-1/2 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground shadow-[var(--shadow-panel)]">
                  <MessageSquare size={13} />
                </span>
                <div className="-ml-3.5 -translate-y-3">
                  <BoardCommentComposer
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
          className="overflow-hidden rounded-md border border-border"
          bgColor="var(--panel)"
          maskColor="color-mix(in srgb, var(--background) 55%, transparent)"
          nodeColor="var(--border-strong)"
          nodeStrokeColor="transparent"
        />}
      </ReactFlow>

      {commentMode && (
        <button
          type="button"
          data-board-comment-mode-hint=""
          className="absolute left-1/2 top-2 z-30 flex h-[42px] -translate-x-1/2 items-center rounded-full border border-primary/30 bg-panel/80 px-3 text-ui-xs text-foreground shadow-[var(--shadow-panel)] backdrop-blur-xl transition-colors hover:bg-panel/95"
          title={t("boardExitCommentMode")}
          aria-label={t("boardExitCommentMode")}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            onExitCommentMode?.();
          }}
        >
          <span className="font-semibold text-primary">{t("boardCommentMode")}</span>
          <span className="mx-1.5 text-muted-foreground">·</span>
          <span className="text-muted-foreground">{t("boardCommentModeHint")}</span>
        </button>
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

      {/* 从线尾长出下一个节点。位置跟着松手的地方,**不是屏幕中央** —— 用户刚把线拉到那儿,
          单子出现在别处等于要他把视线再挪一趟。 */}
      {linkMenu && (
        <>
          {/* 点别处就收起来。铺满整块,但在菜单**下面**。 */}
          <div className="fixed inset-0 z-40" onPointerDown={() => setLinkMenu(null)} />
          {/* 把那条线接着画到菜单上。**画的是一根线,不是一条边** —— 这时还没有第二个节点,
              真的边无从连起;而没有它,松手的一瞬间线就断在半空,像是操作没生效。 */}
          <svg className="pointer-events-none fixed inset-0 z-40 h-full w-full" aria-hidden>
            <path
              d={`M${linkMenu.fromX},${linkMenu.fromY} C${(linkMenu.fromX + linkMenu.screenX) / 2},${linkMenu.fromY} ${(linkMenu.fromX + linkMenu.screenX) / 2},${linkMenu.screenY} ${linkMenu.screenX},${linkMenu.screenY}`}
              className="fill-none stroke-border-strong"
              strokeWidth={1.5}
            />
          </svg>
          <div
            className="fixed z-50 w-56 overflow-hidden rounded-xl border border-border-strong bg-panel p-1 shadow-[var(--shadow-panel)]"
            style={{ left: linkMenu.screenX + 8, top: linkMenu.screenY + 8 }}
          >
            <p className="px-2 py-1.5 text-ui-2xs text-muted-foreground">{t("boardSpawnTitle")}</p>
            {SPAWNABLE_KINDS.map((kind) => {
              const Icon = kindIcon(kind);
              const { label, hint } = kindText(t, kind);
              return (
                <button
                  key={kind}
                  type="button"
                  onClick={() => {
                    spawnLinked(kind, linkMenu.from, { x: linkMenu.x, y: linkMenu.y }, linkMenu.fromIsSource);
                    setLinkMenu(null);
                  }}
                  className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-secondary"
                >
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-secondary text-muted-foreground">
                    <Icon size={14} />
                  </span>
                  <span className="grid min-w-0 gap-0.5">
                    <span className="truncate text-ui-xs text-foreground">{label}</span>
                    <span className="truncate text-ui-2xs text-muted-foreground">{hint}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </>
      )}

      {/* 选中之后才出操作条 —— 没选中时它没有作用对象。 */}
      <ItemToolbar
        nodes={nodes}
        setNodes={setNodes}
        onPickAsset={onPickAsset}
        onSpawn={onGenerate ? spawnLinked : undefined}
        onTrimRequest={onTrim ? (id) => setTrimming((current) => (current === id ? null : id)) : undefined}
        trimmingId={trimming}
        onGroup={groupSelection}
      />

      {/* 空便签:挂写文案的面板。**和图片/视频不是同一张表** —— 写字没有比例、时长、参考图
          这些东西,硬塞进同一个组件里会长出一堆「文本的时候不显示」的分支。 */}
      {composerItem?.kind === "note" && onWrite && (
        <NoteComposer
          key={itemFormResetKey(composerItem)}
          item={composerItem}
          busy={writing === composerItem.id}
          workspaceId={workspaceId}
          //: 上游连过来的素材,**不只是图**:视频抽帧给它看,音频有转写就当材料 ——
          //: 一段片子连到便签,意思就是「照着这段写」。
          upstreamAssets={feeding.assets.map((one) => one.assetId)}
          //: 上游便签的字当**材料**,不是提示词 —— 「接着这段往下写」里,那段是素材,
          //: 用户在框里打的才是指令。
          upstreamTexts={feeding.texts.map((one) => one.text)}
          onFormChange={(form) => patch(composerItem.id, { form })}
          onWrite={({ prompt, providerProfileId, model, assets, context }) => {
            setWriting(composerItem.id);
            return onWrite({ itemId: composerItem.id, prompt, providerProfileId, model, assets, context }).finally(() =>
              setWriting(null),
            );
          }}
        />
      )}

      {/* 剪一段:定起止,产出落到**新节点**上。 */}
      {trimming && onTrim && (() => {
        const node = nodes.find((one) => one.id === trimming);
        const item = node && (node.data as unknown as { item: BoardItem }).item;
        if (!node || !item?.asset_id) return null;
        return (
          <TrimComposer
            key={item.id}
            item={item}
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
              void onTrim({
                //: 产出落到**新的一格**,摆在原件下面 —— 覆盖原件的话,上一版就没了。
                itemId: `${item.kind}-${Date.now().toString(36)}`,
                assetId: item.asset_id as string,
                start,
                end,
                mute,
                x: node.position.x,
                y: node.position.y + (node.height ?? 200) + 60,
              }).finally(() => setTrimming(null));
            }}
          />
        );
      })()}

      {/* 音频:念一段文字。**不是「生成」那条路** —— 出图出片选生成模型,念字选的是音色。 */}
      {composerItem?.kind === "audio" && onSpeak && (
        <AudioComposer
          key={itemFormResetKey(composerItem)}
          item={composerItem}
          busy={itemIsRunning(composerItem)}
          workspaceId={workspaceId}
          //: 上游便签的字**就是要念的内容** —— 让用户再抄一遍,那条线就白连了。
          upstreamText={feeding.texts.map((one) => one.text).join("\n\n")}
          onFormChange={(form) => patch(composerItem.id, { form })}
          onSpeak={({ text, voiceId }) => void onSpeak({ itemId: composerItem.id, text, voiceId })}
        />
      )}

      {/* 选中一个**还没有产出**的图片/视频槽时,底下挂提示词面板 —— 节点本身就是生成单元。 */}
      {composerItem && composerItem.kind !== "note" && composerItem.kind !== "audio" && onGenerate && (
        <NodeComposer
          key={itemFormResetKey(composerItem)}
          item={composerItem}
          models={models ?? []}
          busy={itemIsRunning(composerItem)}
          onPickAsset={onPickAsset}
          workspaceId={workspaceId}
          upstream={feeding.assets}
          upstreamTexts={feeding.texts}
          onFormChange={(form) => patch(composerItem.id, { form })}
          onSubmit={({ prompt, provider, model, parameters, sourceAssets, form }) =>
            void onGenerate({
              kind: composerItem.kind as "image" | "video",
              prompt,
              provider,
              model,
              parameters,
              sourceAssets,
              form,
              itemId: composerItem.id,
            })
          }
        />
      )}
    </div>
  );
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
  onPickAsset,
  onSpawn,
  onTrimRequest,
  trimmingId,
  onGroup,
}: {
  nodes: Node[];
  setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
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
  /** 把当前选中的这几项圈成一组。 */
  onGroup?: () => void;
}) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  const selected = nodes.filter((node) => node.selected);
  // 多选时只给共通的动作 —— 逐个类型的动作在混选下没有一致的含义。
  const single = selected.length === 1 ? selected[0] : null;
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

  const duplicate = () =>
    setNodes((current) => [
      ...current.map((node) => ({ ...node, selected: false })),
      ...current
        .filter((node) => node.selected)
        .map((node) => {
          const source = (node.data as unknown as { item: BoardItem }).item;
          const copy: BoardItem = { ...source, id: `${source.kind}-${Math.random().toString(36).slice(2, 9)}` };
          return {
            ...node,
            id: copy.id,
            // 错开一点放,不然复制出来的正好盖在原件上,看着像什么都没发生。
            position: { x: node.position.x + 24, y: node.position.y + 24 },
            selected: true,
            data: { ...node.data, item: copy },
          };
        }),
    ]);

  return (
    //: 上下浮层都从**节点边框**量同一段距离。类型标签挂在节点外,但不能因此让上方浮层
    //: 另用一套数字 —— 否则一眼看过去就是上疏下密。
    <NodeToolbar nodeId={selected.map((node) => node.id)} isVisible position={Position.Top} offset={BOARD_NODE_PANEL_OFFSET}>
      <div className="nodrag nopan flex items-center gap-1 rounded-full border border-border-strong bg-panel p-1.5 shadow-[var(--shadow-panel)]">
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

        {/* 分组框:**这一组是不是一个整体**。开着的时候拖框会把框里的东西一起带走 ——
            没有它的话,想把一组想法整体挪个位置就得一个个拖。 */}
        {item?.kind === "frame" && (
          <button
            type="button"
            aria-pressed={Boolean(item.move_children)}
            title={t(item.move_children ? "boardMoveChildrenOn" : "boardMoveChildrenOff")}
            className={cn(
              "flex cursor-pointer items-center gap-1.5 rounded-full px-2.5 py-1.5 text-ui-xs transition-colors",
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
            className="flex cursor-pointer items-center gap-1.5 rounded-full px-2.5 py-1.5 text-ui-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
            title={t("boardPreviewTitle")}
            onClick={() =>
              openImagePreview({
                src: item.kind === "image"
                  ? assetPreviewUrl(item.asset_id as string)
                  : assetFileUrl(item.asset_id as string),
                title: item.text || "",
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
              "flex cursor-pointer items-center gap-1.5 rounded-full px-2.5 py-1.5 text-ui-xs transition-colors hover:bg-secondary hover:text-foreground",
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
            className="flex cursor-pointer items-center gap-1.5 rounded-full px-2.5 py-1.5 text-ui-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
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
        {onSpawn && single && item && item.kind !== "frame" && !itemIsRunning(item) && (
          <>
            {(["image", "video", "note", "audio"] as const)
              //: 便签往下接图片,有产出的图片/视频往下接视频 —— 空槽自己都还没有东西可给。
              //: 文案谁都能往下接:给图配一段说明、给便签接着往下写。
              //: 便签往下接图片和音频(有字才接得动),有产出的图片/视频往下接视频;
              //: 文案谁都能往下接。空槽自己都还没有东西可给。
              .filter((kind) => {
                if (kind === "note") return item.kind !== "note" || Boolean((item.text ?? "").trim());
                if (kind === "audio") return item.kind === "note" && Boolean((item.text ?? "").trim());
                if (item.kind === "note") return kind === "image";
                return Boolean(item.asset_id) && kind === "video";
              })
              .map((kind) => (
                <button
                  key={kind}
                  type="button"
                  className="flex cursor-pointer items-center gap-1.5 rounded-full px-2.5 py-1.5 text-ui-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
                  title={
                    kind === "audio"
                      ? t("boardSpawnAudio")
                      : kind === "note"
                        ? t("boardSpawnNote")
                        : item.kind === "note"
                          ? t("boardSpawnImageFromNote")
                          : t("boardSpawnVideoFromImage")
                  }
                  onClick={() =>
                    onSpawn(kind, item.id, {
                      x: single.position.x + (single.width ?? 260) + 60,
                      y: single.position.y + (single.height ?? 180) / 2,
                    })
                  }
                >
                  <Sparkles size={13} />{" "}
                  {/* 文案那一格说的是「生成文案」而不是「生成便签」—— 便签是这张卡片的名字,
                      而用户要的是里面那段字。套同一个模板会说出「Generate Note」这种话。 */}
                  {kind === "note"
                    ? t("boardWriteCopy")
                    : t("boardGenerateKind").replace("{kind}", kindText(t, kind).label)}
                </button>
              ))}
          </>
        )}
        </div>

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
          onClick={() => setNodes((current) => current.filter((node) => !node.selected))}
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
