/**
 * 画板上「一根线能不能连」的规矩,**只此一处**:单格拉线(React Flow 的 isValidConnection)、从选区框的统一出口一次
 * 连到一格、从统一出口拉出来新建一格,读的都是这一份。各写一份的话,单格连得上的一对,批量里却被跳过(或反过来)。
 *
 * 规矩只管**建线的那一刻**:存下来的线不因规则而失效(ADR 0025 决定 4)。线连上之后「它给下游什么」—— 槽位里挂
 * 哪份素材(`source_assets[].from`)、哪个字段绑哪一格(`bindings`)—— 照旧由面板照上游写、服务端按线摘
 * (canvas._drop_detached_bindings),批量连的线和单格连的线在这一点上没有区别。
 */
import type { BoardItem } from "@/api/client";

/** 一根线连不上的原因。界面按它说「几条没连上」。 */
export type LinkRefusal =
  /** 自己连自己。 */
  | "self"
  /** 分组框只是圈东西的框,不进也不出线。 */
  | "notLinkable"
  /** 这两格之间已经有这根线了。 */
  | "duplicate"
  /** 时间线格只收视频 / 图片 / 音频(连进来就是接到末尾,ADR 0030 §3)。 */
  | "timelineTakesMedia";

type Cell = Pick<BoardItem, "id" | "kind">;
type Link = { source: string; target: string };

const TIMELINE_SOURCES: ReadonlySet<BoardItem["kind"]> = new Set(["video", "image", "audio"]);

/** 从 `source` 连一根线到 `target` 行不行;行回 null。 */
export function linkRefusal(source: Cell, target: Cell, edges: readonly Link[]): LinkRefusal | null {
  if (source.id === target.id) return "self";
  if (!canLink(source) || !canLink(target)) return "notLinkable";
  if (edges.some((edge) => edge.source === source.id && edge.target === target.id)) return "duplicate";
  if (target.kind === "sequence" && !TIMELINE_SOURCES.has(source.kind)) return "timelineTakesMedia";
  return null;
}

/** 分组框只是圈东西的框,不进也不出线。 */
export function canLink(cell: Cell): boolean {
  return cell.kind !== "frame";
}

/**
 * 选区框的统一出口从哪几格连出去:选中了两格以上时,其中连得出线的那几格(分组框不算 —— 框选时常常把框也框进来);
 * 不到两格回空(单格用它自己的出口)。**按从左到右排**(x 相同再按 y):连进时间线格时一段一段照这个顺序接到末尾,
 * 和画面上的先后一致 —— 照节点数组的顺序接的话,先放上画布的那张排在前面,和人看到的对不上。
 */
export function selectionSources<C extends Cell & { x: number; y: number; selected?: boolean }>(cells: readonly C[]): C[] {
  const picked = cells.filter((cell) => cell.selected);
  if (picked.length < 2) return [];
  return picked.filter(canLink).sort((a, b) => a.x - b.x || a.y - b.y);
}

/**
 * 这几格一次都连到 `target`:按单格同一条规矩逐根判,连得上的按 `sources` 的顺序交回。
 * `refused` 只数**真没连上**的(分组框、时间线格不收的);已经连着的不算 —— 线本来就在,结果就是用户要的。
 * `target` 自己在这几格里(拖到选中的另一格上)也不算没连上 —— 它就是终点。
 */
export function batchLinks(
  sources: readonly Cell[],
  target: Cell,
  edges: readonly Link[],
): { links: Link[]; refused: number } {
  const links: Link[] = [];
  let refused = 0;
  for (const source of sources) {
    const why = linkRefusal(source, target, [...edges, ...links]);
    if (why === null) links.push({ source: source.id, target: target.id });
    else if (why !== "self" && why !== "duplicate") refused += 1;
  }
  return { links, refused };
}

/** 从一格的入口拉出来新建一格:新的一格是它的上游,哪几种格子连得进它。 */
export function spawnableBefore<K extends BoardItem["kind"]>(target: Cell, kinds: readonly K[]): K[] {
  return kinds.filter((kind) => linkRefusal({ id: "__new__", kind }, target, []) === null);
}

/** 从这几格拉出来新建一格:哪几种格子**每一格都连得上**(新的一格是它们共同的下游)。 */
export function spawnableFor<K extends BoardItem["kind"]>(sources: readonly Cell[], kinds: readonly K[]): K[] {
  const fresh = "__new__";
  return kinds.filter((kind) => sources.every((source) => linkRefusal(source, { id: fresh, kind }, []) === null));
}
