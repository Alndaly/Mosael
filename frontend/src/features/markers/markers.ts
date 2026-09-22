/**
 * 画布上的**标记**:一个位置书签,不是节点。
 *
 * 工作流和创意画板共用这一份 —— 两个页面的画布不同(一个存 graph.nodes,一个存 canvas.items),
 * 但"这是一个位置书签、它绑了哪个键、这个键能不能绑"这三件事完全一样。各写一遍的话,
 * 冲突规则就会在其中一边漂掉,而漂掉的那一半正是用户会撞上的那一半。
 *
 * 后端有同一份形状与查重规则(backend/app/domain/markers.py):这里拦的是**能不能配**
 * (还要和应用自己的快捷键比),后端拦的是**能不能存**(数据本身的不变量)。归一必须两边
 * 一字不差,所以它由 `contracts/marker-shortcut-cases.json` 钉住,两侧跑同一份语料。
 */

import type { Node } from "@xyflow/react";

import type { MessageKey } from "@/app/messages";
import { normalizeCombo, reservedOwner, type Combo } from "@/lib/shortcuts";

export interface CanvasMarker {
  id: string;
  name: string;
  x: number;
  y: number;
  /** 没绑键的标记是合法的:它仍然出现在标记列表里,点一下就能跳。 */
  shortcut?: Combo;
}

export const MAX_MARKERS = 64;

/** 这个组合为什么不能用。`null` = 能用。 */
export type MarkerShortcutConflict =
  | { reason: "invalid" }
  | { reason: "reserved"; owner: MessageKey }
  | { reason: "marker"; markerName: string };

/**
 * 能不能把 `raw` 绑给 `selfId` 这个标记。
 *
 * **撞了就不给配**,而不是配上去之后再看谁先响应 —— 后者的表现是"这个快捷键有时候好使",
 * 而用户永远查不出来是被谁抢走的。
 */
export function markerShortcutConflict(
  raw: string,
  markers: CanvasMarker[],
  selfId: string,
): MarkerShortcutConflict | null {
  const combo = normalizeCombo(raw);
  if (!combo) return { reason: "invalid" };
  const owner = reservedOwner(combo);
  if (owner) return { reason: "reserved", owner };
  const taken = markers.find((one) => one.id !== selfId && one.shortcut === combo);
  if (taken) return { reason: "marker", markerName: taken.name };
  return null;
}

/** 「标记 1」「标记 2」… 按**已占用的名字**找空位,删掉中间一个再新建正好补回去。 */
export function nextMarkerName(stem: string, markers: CanvasMarker[]): string {
  const taken = new Set(markers.map((one) => one.name));
  for (let index = 1; ; index += 1) {
    const candidate = `${stem} ${index}`;
    if (!taken.has(candidate)) return candidate;
  }
}

export function newMarkerId(markers: CanvasMarker[]): string {
  const taken = new Set(markers.map((one) => one.id));
  for (let index = 1; ; index += 1) {
    const candidate = `marker-${index}`;
    if (!taken.has(candidate)) return candidate;
  }
}

/** 按下的这个键归哪个标记?没有就是 null。 */
export function markerForCombo(markers: CanvasMarker[], combo: Combo): CanvasMarker | null {
  return markers.find((one) => one.shortcut === combo) ?? null;
}

/**
 * 标记在 React Flow 里也是节点(拖动、选中、⌫ 删除因此都白拿),但 **id 带前缀**。
 *
 * 图里的 `markers` 和 `nodes` 是两份列表,不带前缀的话,一个和节点(或画板项)重名的标记
 * 会把它顶掉。两块画布此前各写一个 `"marker:"` —— 两个字符串碰巧相等,而它们一旦分岔,
 * 表现是"标记读不回来了 / 和节点互相顶掉":不报错,只在重名时才出现。
 */
export const MARKER_PREFIX = "marker:";

/**
 * 标记 → React Flow 节点。两块画布共用这一份。
 *
 * `zIndex` 由**画布自己给**:规则是"旗子压在本画布所有内容之上",而"所有内容"是哪几层、
 * 各是多少,只有那块画布知道。它要从画布自己的层次表里取(`LAYERS`),**不许在调用处现挑
 * 一个数** —— 此前两块画布一个写 2、一个写 950,不是谁错了,是"最上面"在两边各自是一个
 * 凭手感挑的常数,而没有任何地方写下过那条规则。棘轮:`features/canvasLayers.test.ts`。
 */
export function toMarkerNodes(markers: CanvasMarker[], zIndex: number): Node[] {
  return markers.map((marker) => ({
    id: MARKER_PREFIX + marker.id,
    type: "marker",
    position: { x: marker.x, y: marker.y },
    data: { marker },
    zIndex,
    connectable: false,
  }));
}
