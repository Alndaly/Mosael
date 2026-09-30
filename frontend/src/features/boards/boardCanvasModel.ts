/**
 * 画板画布的纯函数:React Flow 节点和画板数据之间的换算、选择、复制、评论锚点、查找缩放。
 * 不碰 React —— 画布组件(BoardCanvas)和它的几个钩子都从这里取。
 */
import type { Edge, Node } from "@xyflow/react";

import type { BoardCanvas as Canvas, BoardItem, CollaborationComment } from "@/api/client";
import { DEFAULT_SIZE, type MediaKind } from "@/features/boards/boardNodes";
import { copiedItem } from "@/features/boards/boardItemState";
import type { CanvasMarker } from "@/features/markers/markers";

/** 让上层开素材选择器(见 BoardCanvas 的 Props.onPickAsset)。画布和操作条共用这一个形状。 */
export type BoardPickAsset = (kind: MediaKind | "media", place: (assetId: string) => void, options?: { onBoard?: string[] }) => void;

/**
 * 这块画布的层次 —— **一处说了算**。
 *
 * 规则是"旗子压在所有内容之上"。它此前是调用处一个凭手感挑的 `zIndex: 2`,而工作流那块画布
 * 写的是 950:两个数不是谁错了,是同一条规则在两边各挑了一个常数,而规则本身没写在任何地方。
 * 加一种新节点类型时,该挑几没有参照系可查。
 */
export const LAYERS = {
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

export function toNodes(items: BoardItem[]): Node[] {
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
  const rewired = copies.map((node) => {
    const item = (node.data as unknown as { item: BoardItem }).item;
    const form = rewiredForm(item.form, renamed);
    return form === item.form ? node : { ...node, data: { ...node.data, item: { ...item, form } } };
  });
  return {
    nodes: [...nodes.map((node) => ({ ...node, selected: false })), ...rewired],
    edges: [...edges, ...copiedEdges],
  };
}

/**
 * 副本的表单里「顺着线接上的东西」跟着线走:上游也一起复制了的,出处改记成新的那一格(线也复制了)。
 * **三处用同一张改名表**:槽位里挂的素材(`source_assets[].from`)、这一格自己的产出者的字段绑定(`bindings`)、
 * 每一项能力的绑定(`abilities[*].bindings`)。此前只改了第一处,一对连着的格子复制出来,副本的字段还绑着原件 ——
 * 副本上没有那根线,存的时候服务端把绑定摘掉,副本就不再从它的上游取值了。
 *
 * 没一起复制的上游原样留着,副本上没有那根线,存的时候服务端摘掉(canvas._drop_detached_bindings)——
 * 和删掉那根线是同一条规则。什么都没改就回原来那一份。
 */
export function rewiredForm(form: BoardItem["form"], renamed: ReadonlyMap<string, string>): BoardItem["form"] {
  if (!form) return form;
  const moves = (from: string | undefined) => Boolean(from && renamed.has(from));
  type Bindings = NonNullable<NonNullable<BoardItem["form"]>["bindings"]>;
  const rebind = (bindings: Bindings | undefined): Bindings | undefined =>
    bindings && Object.values(bindings).some((refs) => refs.some((ref) => moves(ref.from)))
      ? Object.fromEntries(
          Object.entries(bindings).map(([field, refs]) => [
            field,
            refs.map((ref) => (moves(ref.from) ? { ...ref, from: renamed.get(ref.from) as string } : ref)),
          ]),
        )
      : bindings;
  let next = form;
  if (form.source_assets?.some((one) => moves(one.from))) {
    next = {
      ...next,
      source_assets: form.source_assets.map((one) => (moves(one.from) ? { ...one, from: renamed.get(one.from as string) } : one)),
    };
  }
  const bindings = rebind(form.bindings);
  if (bindings !== form.bindings) next = { ...next, bindings };
  if (form.abilities) {
    let changed = false;
    const abilities = Object.fromEntries(
      Object.entries(form.abilities).map(([producer, setting]) => {
        const moved = rebind(setting.bindings);
        if (moved === setting.bindings) return [producer, setting];
        changed = true;
        return [producer, { ...setting, bindings: moved }];
      }),
    );
    if (changed) next = { ...next, abilities };
  }
  return next;
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

export type CanvasCommentAnchor = NonNullable<CollaborationComment["anchor"]>;
export type ScreenPoint = { x: number; y: number };

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
