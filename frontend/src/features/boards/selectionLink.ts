/**
 * 选区框的统一出口(多选之后一次连线)的几何与判定:框在哪、出口在哪、拖着它的时候画哪几根预览线、指针底下是哪一格、
 * 每一根连不连得上。全是纯函数 —— 拖动本身(指针事件、Esc)在 BoardSelectionOutlet,规矩本身(一根线能不能连)
 * 在 boardLinks,这里只把两者接起来,好单独测。
 *
 * 坐标一律是**流坐标**(画布坐标):平移缩放时由画的那一层换成屏幕坐标,这里不认视口。
 */
import type { BoardItem } from "@/api/client";
import { linkRefusal } from "@/features/boards/boardLinks";

export type XY = { x: number; y: number };
export type Rect = XY & { width: number; height: number };
/** 画布上的一格:种类(规矩看它)+ 它占的那块地方。 */
export type PlacedCell = Pick<BoardItem, "id" | "kind"> & Rect;

/** 几块合起来的外接矩形。一块都没有回 null。 */
export function boundsOf(rects: readonly Rect[]): Rect | null {
  if (rects.length === 0) return null;
  const left = Math.min(...rects.map((one) => one.x));
  const top = Math.min(...rects.map((one) => one.y));
  const right = Math.max(...rects.map((one) => one.x + one.width));
  const bottom = Math.max(...rects.map((one) => one.y + one.height));
  return { x: left, y: top, width: right - left, height: bottom - top };
}

/** 一格的出口锚点:右边中点。格子自己的出口(boardNodes 的 Ports)就贴在右边、竖直居中,预览线和真线从同一处出来。 */
export function outletOf(rect: Rect): XY {
  return { x: rect.x + rect.width, y: rect.y + rect.height / 2 };
}

/** 一格的入口锚点:左边中点。悬在一格上时预览线接到这儿 —— 松手之后那根真线就是从这儿接进去的。 */
export function inletOf(rect: Rect): XY {
  return { x: rect.x, y: rect.y + rect.height / 2 };
}

const contains = (rect: Rect, point: XY) =>
  point.x >= rect.x && point.x <= rect.x + rect.width && point.y >= rect.y && point.y <= rect.y + rect.height;

/**
 * 指针底下是哪一格。叠着的取画在上面的那一格(数组里靠后的)。
 *
 * **分组框不算**:它不进线(boardLinks),落在框里的空白处就是落在空白处 —— 弹「新建一格」,新的一格正好落在框里。
 * 算作目标的话,拖进框里的那一下只会得到一句「没连上」。
 */
export function cellAt(point: XY, cells: readonly PlacedCell[]): PlacedCell | null {
  for (let index = cells.length - 1; index >= 0; index -= 1) {
    const cell = cells[index];
    if (cell.kind !== "frame" && contains(cell, point)) return cell;
  }
  return null;
}

/**
 * 一根预览线的样子:`draft` 还没悬在哪一格上(和拖线途中那根一样);`link` 悬在一格上、这一根连得上(已经连着的也算 ——
 * 松手之后它确实连着);`refused` 这一根连不上,松手会被跳过。
 */
export type DraftTone = "draft" | "link" | "refused";
export type DraftLine = { id: string; from: XY; to: XY; tone: DraftTone };

export interface SelectionDraft {
  /** 指针底下那一格;在空白处是 null。 */
  target: string | null;
  /** 悬着的那一格整体怎么样:有一根连得上就是 `link`,一根都连不上是 `refused`;不在格子上是 null。 */
  verdict: "link" | "refused" | null;
  lines: DraftLine[];
}

/**
 * 拖着统一出口、指针在 `point` 时的样子:每个源从自己的出口画一根线到指针;悬在一格上时线头吸到那一格的入口上
 * (和单格拉线吸到接点上一个手感),每一根按单格同一条规矩判。
 * 终点就是源里的一格(拖到选中的另一格上)时,它自己那一根不画 —— 它就是终点。
 */
export function selectionDraft(
  sources: readonly PlacedCell[],
  cells: readonly PlacedCell[],
  edges: readonly { source: string; target: string }[],
  point: XY,
): SelectionDraft {
  const target = cellAt(point, cells);
  const to = target ? inletOf(target) : point;
  const lines: DraftLine[] = sources
    .filter((source) => source.id !== target?.id)
    .map((source) => {
      const refusal = target ? linkRefusal(source, target, edges) : null;
      const tone: DraftTone = !target ? "draft" : refusal === null || refusal === "duplicate" ? "link" : "refused";
      return { id: source.id, from: outletOf(source), to, tone };
    });
  const verdict = !target ? null : lines.some((line) => line.tone === "link") ? "link" : "refused";
  return { target: target?.id ?? null, verdict, lines };
}
