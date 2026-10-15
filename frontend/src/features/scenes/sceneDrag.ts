import type { SceneContent, SceneObject } from "@/api/domains/scenes";

import { objectTree, withDescendants } from "./sceneGraph";

/**
 * 在「场景中的物体」列表里挪一个物体:**落在哪一行、落在一行的哪一段**。
 *
 * 「落点在哪儿、落不落得下」只写这一次:指针拖拽(dnd-kit,见 SceneObjectTree)和键盘
 * (⌥↑/⌥↓,见 SceneStudio 的快捷键)都走它 —— 两条路各写一份的话,「拖进去的」和「按键移的」
 * 迟早在环、深度这些边角上分家。
 *
 * 落点分三段(和访达、Notion 的树一样):
 *
 * - **上 30% / 下 30%** —— 排在目标行的前面 / 后面,和它同一个父级(父级是根就是根);
 * - **中间 40%** ——「放进去」,**只有组收**(后端 `types.py` 的 `valid_hierarchy`:只有
 *   `kind == "group"` 能当父级)。非组的行没有这一段:它的中间按上下半分,仍然是排序。
 *
 * 另外,列表末尾那条空白(`ROOT_DROP_ID`)是**根层的末尾** —— 从组里拖出来时最顺手的一处,
 * 一份被整组包起来的场景也只有它一个出口。
 *
 * 落不下去的一律返回 null / false —— 界面据此**不画落点**,松手也什么都不写。这比"先画上,
 * 松手再回弹"诚实:落点只出现在真能落的地方。
 */
export type DropZone = "before" | "inside" | "after";

/** 列表末尾那条空白(「放到最外层」)。用一个不可能撞上物体 id 的常量,和 SessionList 的 `__ungrouped__` 同一套。 */
export const ROOT_DROP_ID = "__scene-root__";

/** 一行上下各占这么多是「排在它前/后」,中间留给「放进去」。 */
const EDGE_BAND = 0.3;

/**
 * 后端一条链最多 16 个物体(`valid_hierarchy` 里 `len(seen) > 16` 就拒),所以最深的那个
 * 最多在第 15 层(顶层算 0)。前端先挡住:不然拖完看着好好的,保存回一个 400。
 */
const MAX_LEVEL = 15;

/** 指针落在这一行的哪一段。`group` 才可能有 `inside`。 */
export function dropZoneFor(
  pointerY: number,
  top: number,
  height: number,
  group: boolean,
): DropZone {
  // 量不到高度(还没排版)时别乱猜:组按"放进去",别的按"排在后面"。
  if (!(height > 0)) return group ? "inside" : "after";
  if (pointerY < top + height * EDGE_BAND) return "before";
  if (pointerY > top + height * (1 - EDGE_BAND)) return "after";
  if (group) return "inside";
  return pointerY < top + height / 2 ? "before" : "after";
}

/**
 * 这个物体**长在哪个父级下面**。
 *
 * 父级已经不在了(手工改过的场景)就当根 —— 和 `objectTree` 同一条规矩:那里也是按"在不在"
 * 分桶的,两边不一致的话,落点算出来的位置和画出来的位置会差一层。
 */
function parentOf(content: SceneContent, object: SceneObject): string | null {
  const parent = object.parent_id;
  if (!parent) return null;
  return content.objects.some((one) => one.id === parent) ? parent : null;
}

/** `id` 自己在第几层(顶层 0);有环也不转圈。 */
function levelOf(content: SceneContent, id: string): number {
  const byId = new Map(content.objects.map((one) => [one.id, one]));
  const seen = new Set([id]);
  let level = 0;
  let parent = byId.get(id)?.parent_id ?? null;
  while (parent && byId.has(parent) && !seen.has(parent)) {
    seen.add(parent);
    level += 1;
    parent = byId.get(parent)!.parent_id ?? null;
  }
  return level;
}

/** `id` 下面还压着几层。 */
function heightOf(content: SceneContent, id: string): number {
  const seen = new Set([id]);
  let frontier = new Set([id]);
  let height = 0;
  while (frontier.size) {
    const next = new Set<string>();
    for (const one of content.objects) {
      if (one.parent_id && frontier.has(one.parent_id) && !seen.has(one.id)) {
        seen.add(one.id);
        next.add(one.id);
      }
    }
    if (!next.size) break;
    height += 1;
    frontier = next;
  }
  return height;
}

/**
 * 一个物体能不能挂到 `parentId` 底下。三条,和后端的校验一一对应:
 * 父级得存在、**得是组**、不能是自己的后代(环),再加上深度封顶。
 */
function accepts(content: SceneContent, activeId: string, parentId: string | null): boolean {
  if (parentId === null) return true;
  const parent = content.objects.find((one) => one.id === parentId);
  if (!parent || parent.kind !== "group") return false;
  if (withDescendants(content, activeId).has(parentId)) return false;
  return levelOf(content, parentId) + 1 + heightOf(content, activeId) <= MAX_LEVEL;
}

/** 和 `id` 同一个父级的那些物体(**含它自己**),按数组序 —— 也就是列表里的先后。 */
export function siblingsOf(content: SceneContent, id: string): SceneObject[] {
  const self = content.objects.find((one) => one.id === id);
  if (!self) return [];
  const parent = parentOf(content, self);
  return content.objects.filter((one) => parentOf(content, one) === parent);
}

/**
 * 落下去之后的 `objects` 数组;落不下去返回 null。
 *
 * **只动数组的顺序和那一个 `parent_id`,别的一律不碰**:同一个父级里的先后完全由数组序决定
 * (`objectTree` 按父级分桶后再走数组),所以插在目标行的前一位/后一位,在它那一桶里就是
 * 前一位/后一位 —— 中间隔着别的桶的物体不影响。
 */
function plan(
  content: SceneContent,
  activeId: string,
  overId: string,
  zone: DropZone,
): SceneObject[] | null {
  const active = content.objects.find((one) => one.id === activeId);
  if (!active || activeId === overId) return null;
  const without = content.objects.filter((one) => one.id !== activeId);

  let parentId: string | null;
  let at: number;
  if (overId === ROOT_DROP_ID) {
    // 列表末尾那条空白 = 根层的末尾。
    parentId = null;
    at = without.length;
  } else {
    const over = without.find((one) => one.id === overId);
    if (!over) return null;
    if (zone === "inside") {
      // 只有组收 —— 非组这里直接落不下去(界面上也不会给出这一段)。
      if (over.kind !== "group") return null;
      parentId = over.id;
      // 放进组里 = 排在那一桶的末尾:空的组就紧跟在它后面。
      const bucket = without.filter((one) => parentOf(content, one) === parentId);
      const last = bucket[bucket.length - 1];
      at = last ? without.indexOf(last) + 1 : without.indexOf(over) + 1;
    } else {
      parentId = parentOf(content, over);
      at = without.indexOf(over) + (zone === "after" ? 1 : 0);
    }
  }
  if (!accepts(content, activeId, parentId)) return null;
  return [...without.slice(0, at), { ...active, parent_id: parentId }, ...without.slice(at)];
}

/** 落得下吗。界面用它决定画不画落点。 */
export function canDrop(
  content: SceneContent,
  activeId: string,
  overId: string,
  zone: DropZone,
): boolean {
  return plan(content, activeId, overId, zone) !== null;
}

/**
 * 走一步:**看得见的树没变就返回 null**(别为一次原地松手往撤销栈里塞一条空记录),落不下去也返回 null。
 */
export function moveObject(
  content: SceneContent,
  activeId: string,
  overId: string,
  zone: DropZone,
): SceneContent | null {
  const objects = plan(content, activeId, overId, zone);
  if (!objects) return null;
  const next = { ...content, objects };
  return treeOrder(next) === treeOrder(content) ? null : next;
}

/** 树画出来的那个样子(每行的层数 + 先后)—— 用户看见的就是它,不受数组里跨桶的排法影响。 */
function treeOrder(content: SceneContent): string {
  return objectTree(content)
    .map((row) => `${row.depth}:${row.object.id}`)
    .join("|");
}
