/**
 * 画板上「一根线能不能连」的规矩,**只此一处**:单格拉线(React Flow 的 isValidConnection)、多选之后一次连到一格、
 * 多选之后拉出来新建一格,读的都是这一份。各写一份的话,单格连得上的一对,批量里却被跳过(或反过来)。
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
  if (source.kind === "frame" || target.kind === "frame") return "notLinkable";
  if (edges.some((edge) => edge.source === source.id && edge.target === target.id)) return "duplicate";
  if (target.kind === "sequence" && !TIMELINE_SOURCES.has(source.kind)) return "timelineTakesMedia";
  return null;
}

/**
 * 拉线的那一格要带上哪几格一起连:它在一组选中的格子里(选中了两格以上)就是这一组,否则就是它自己。
 * 分组框不算 —— 框选时常常把框也框进来,它本来就连不了线。
 */
export function linkSources(from: Cell & { selected?: boolean }, cells: readonly (Cell & { selected?: boolean })[]): Cell[] {
  const picked = cells.filter((cell) => cell.selected && cell.kind !== "frame");
  if (!from.selected || picked.length < 2) return [from];
  return picked;
}

/**
 * 这几格一次都连到 `target`:按单格同一条规矩逐根判,连得上的交回,连不上的数一数(界面说「几条没连上」)。
 * `target` 自己在这几格里(从选中的一格拉到选中的另一格)不算没连上 —— 它就是终点。
 */
export function batchLinks(
  sources: readonly Cell[],
  target: Cell,
  edges: readonly Link[],
): { links: Link[]; refused: number } {
  const links: Link[] = [];
  let refused = 0;
  for (const source of sources) {
    if (source.id === target.id) continue;
    if (linkRefusal(source, target, [...edges, ...links])) refused += 1;
    else links.push({ source: source.id, target: target.id });
  }
  return { links, refused };
}

/** 从这几格拉出来新建一格:哪几种格子**每一格都连得上**(新的一格是它们共同的下游)。 */
export function spawnableFor<K extends BoardItem["kind"]>(sources: readonly Cell[], kinds: readonly K[]): K[] {
  const fresh = "__new__";
  return kinds.filter((kind) => sources.every((source) => linkRefusal(source, { id: fresh, kind }, []) === null));
}
