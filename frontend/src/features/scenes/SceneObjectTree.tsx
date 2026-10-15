import React from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragMoveEvent,
} from "@dnd-kit/core";
import {
  Box,
  Boxes,
  ChevronRight,
  Eye,
  EyeOff,
  Folder,
  Lightbulb,
  Trash2,
  Video,
} from "lucide-react";

import type { SceneContent, SceneObject } from "@/api/domains/scenes";
import { useI18n } from "@/app/preferences";
import { useDndAccessibility } from "@/components/app/dndAccessibility";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";

import { canDrop, dropZoneFor, ROOT_DROP_ID, type DropZone } from "./sceneDrag";
import { hiddenObjectIds, objectTree } from "./sceneGraph";

/** 列表里那个小图标。**组、相机、灯要分得出来** —— 全是同一个方块的话,树的结构没人看得懂。 */
function ObjectKindIcon({ kind }: { kind: SceneObject["kind"] }) {
  if (kind === "group") return <Folder size={14} />;
  if (kind === "camera") return <Video size={14} />;
  if (kind === "light") return <Lightbulb size={14} />;
  if (kind === "model") return <Boxes size={14} />;
  return <Box size={14} />;
}

/** 落点:哪一行、落在它的哪一段。 */
interface DropTarget {
  id: string;
  zone: DropZone;
}

/** 指针此刻的纵坐标。拖动的**起手事件**(pointerdown)加上累计位移就是它 —— dnd-kit 的事件里没有现成的。 */
function pointerY(event: DragMoveEvent | DragEndEvent): number | null {
  const activator = event.activatorEvent as { clientY?: number } | null;
  if (typeof activator?.clientY !== "number") return null;
  return activator.clientY + event.delta.y;
}

/**
 * 「场景中的物体」这份列表:一棵可以拖着改结构、也可以按 ⌥↑/⌥↓ 排的树。
 *
 * - **拖着排序**:落在某一行的上下三成 = 排在它前/后,和它同一个父级;顺序落到 `objects` 数组里
 *   (见 sceneDrag 的 `plan`)。
 * - **拖进 / 拖出组**:落在组行的中间 = 收进那个组;落在顶层某个物体的前后、或列表末尾那条空白
 *   (`ROOT_DROP_ID`)= 回到根层(`parent_id = null`)。非组收不了,环和超深也落不下 ——
 *   这些落点**根本不画**,松手什么也不写。
 * - **折叠的组照样能接**:那一行还在,落进去之后**自动展开**,好让人看见东西去哪了。
 * - 读写全走外层的 `onMove`(一次 `update`):撤销栈和自动保存都不另开一份。
 *
 * 一条 `useDraggable` + 一条 `useDroppable` 挂在同一行上(和 dnd-kit 的 sortable 一样两用),
 * 拖柄是名字那一格:折叠箭头、眼睛、删除三颗钮照旧只做自己的事,不会一按就拖起来。
 */
export function SceneObjectTree({
  content,
  selected,
  collapsed,
  busy,
  onSelect,
  onFocusView,
  onToggleCollapse,
  onExpandGroup,
  onToggleHidden,
  onRemove,
  onMove,
}: {
  content: SceneContent;
  selected: string | null;
  collapsed: ReadonlySet<string>;
  busy: boolean;
  onSelect: (id: string) => void;
  /** 双击:把焦点还给视口(照旧)。 */
  onFocusView: () => void;
  onToggleCollapse: (id: string) => void;
  /** 拖进一个折叠着的组之后把它展开:东西不能就这么消失在收起来的那一行里。 */
  onExpandGroup: (id: string) => void;
  onToggleHidden: (id: string) => void;
  onRemove: (id: string) => void;
  onMove: (activeId: string, overId: string, zone: DropZone) => void;
}) {
  const t = useI18n();
  const rows = React.useMemo(() => objectTree(content, collapsed), [content, collapsed]);
  // 藏在一个藏起来的组里的行也淡下去,但斜体只有自己藏了才有(见下面那行 data-hidden)。
  const inheritedHidden = React.useMemo(() => hiddenObjectIds(content.objects), [content.objects]);
  const byId = React.useMemo(
    () => new Map(content.objects.map((one) => [one.id, one])),
    [content],
  );
  const [dragId, setDragId] = React.useState<string | null>(null);
  const [drop, setDrop] = React.useState<DropTarget | null>(null);
  // 6px 起手:和剪辑页拖素材、对话列表拖分组同一套 —— 不吃普通点击,也不吃右键菜单。
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const dndAccessibility = useDndAccessibility();

  /**
   * 落点。**只在真能落的地方返回**(`canDrop`):落不下(非组、环、太深、原地)就没有落点,
   * 也就没有"松手又弹回去"。
   */
  const resolve = (event: DragMoveEvent | DragEndEvent): DropTarget | null => {
    const over = event.over;
    if (!over) return null;
    const activeId = String(event.active.id);
    const overId = String(over.id);
    if (overId === ROOT_DROP_ID) {
      return canDrop(content, activeId, ROOT_DROP_ID, "after") ? { id: ROOT_DROP_ID, zone: "after" } : null;
    }
    const target = byId.get(overId);
    if (!target) return null;
    const y = pointerY(event);
    const zone = y === null
      ? target.kind === "group"
        ? "inside"
        : "after"
      : dropZoneFor(y, over.rect.top, over.rect.height, target.kind === "group");
    return canDrop(content, activeId, overId, zone) ? { id: overId, zone } : null;
  };
  /** 同一次拖动里指针挪一下会来很多次 —— 落点没变就别再 set 一遍(否则整份列表跟着重画)。 */
  const showDrop = (next: DropTarget | null) =>
    setDrop((was) => (was?.id === next?.id && was?.zone === next?.zone ? was : next));

  // 落点只可能是"某一行"或末尾那条空白(见 sceneDrag):被拖的那一行自己不算,指针不在
  // 任何一行上时才轮到那条空白。这里**不做"离谁最近"的兜底** —— 拖到列表外面(视口、别的
  // 面板)就该是"没地方落",而不是"落到最近的那一行上"。
  const collisionDetection = React.useCallback<CollisionDetection>((args) => {
    const hits = pointerWithin(args).filter(
      (hit) => String(hit.id) !== String(args.active.id) && hit.id !== ROOT_DROP_ID,
    );
    return hits.length ? hits : pointerWithin(args).filter((hit) => hit.id === ROOT_DROP_ID);
  }, []);

  const settle = (event: DragEndEvent) => {
    const target = resolve(event);
    setDragId(null);
    setDrop(null);
    if (!target) return;
    // 落进折叠着的组:先把它打开,再写回 —— 不然刚放进去的东西立刻不见。
    if (target.zone === "inside") onExpandGroup(target.id);
    onMove(String(event.active.id), target.id, target.zone);
  };

  return (
    <DndContext
      sensors={sensors}
      accessibility={dndAccessibility}
      collisionDetection={collisionDetection}
      onDragStart={(event) => {
        setDragId(String(event.active.id));
        setDrop(null);
      }}
      onDragMove={(event) => showDrop(resolve(event))}
      onDragEnd={settle}
      onDragCancel={() => {
        setDragId(null);
        setDrop(null);
      }}
    >
      {/* **按树的顺序画,缩进按层数来。** 此前是数组原样铺开、缩进写成
          `o.parent_id ? 24 : 10` —— 只有两级,组里再放组和它的兄弟一样平;
          而把一个物体移进组之后那一行也不会挪到组下面,看上去像没生效。 */}
      <div className="scene-object-list" role="tree" aria-label={t("sceneObjects")}>
        {rows.map(({ object: o, depth, children }) => (
          <SceneObjectRow
            key={o.id}
            object={o}
            depth={depth}
            childCount={children}
            selected={selected === o.id}
            collapsed={collapsed.has(o.id)}
            inherited={inheritedHidden.has(o.id)}
            busy={busy}
            dragging={dragId === o.id}
            drop={drop?.id === o.id ? drop.zone : undefined}
            onSelect={onSelect}
            onFocusView={onFocusView}
            onToggleCollapse={onToggleCollapse}
            onToggleHidden={onToggleHidden}
            onRemove={onRemove}
          />
        ))}
        {/* 列表末尾那条空白:拖到根层的末尾(从组里拖出来最顺手的一处)。
            没有它就只剩"落在某个顶层物体的前后"一条路 —— 一份被整组包起来的场景会没有出口。
            它不占树的位置(`aria-hidden`),高度也只有一条线那么宽。 */}
        <SceneRootDrop active={drop?.id === ROOT_DROP_ID} />
      </div>
      {/* 拖起来时跟手的那一片 —— 没有它,拖动中的行只是原地变淡,看不出自己在拖什么。 */}
      <DragOverlay dropAnimation={null}>
        {dragId && byId.has(dragId) ? (
          <div className="scene-object-ghost">
            <ObjectKindIcon kind={byId.get(dragId)!.kind} />
            <span>{byId.get(dragId)!.name}</span>
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}

/** 最外层那条落点。`data-drop` 只用来画线,别的什么都不做。 */
function SceneRootDrop({ active }: { active: boolean }) {
  const { setNodeRef } = useDroppable({ id: ROOT_DROP_ID });
  return <div ref={setNodeRef} className="scene-object-tail" data-drop={active ? "after" : undefined} aria-hidden="true" />;
}

/**
 * 一行。**可拖、可落,挂的是同一个节点**(名字那一格是拖柄)。
 *
 * aria 照旧归这一行:`role="treeitem"`、层级、有没有展开 —— dnd-kit 给的那套属性只落在名字那颗
 * 按钮上(它本来就是按钮),不然 `role="button"` 会把 `treeitem` 盖掉,树就读不出来了。读屏的
 * "可以按住拖动"那句说明也从那儿来(见 components/app/dndAccessibility)。
 */
function SceneObjectRow({
  object: o,
  depth,
  childCount,
  selected,
  collapsed,
  inherited,
  busy,
  dragging,
  drop,
  onSelect,
  onFocusView,
  onToggleCollapse,
  onToggleHidden,
  onRemove,
}: {
  object: SceneObject;
  depth: number;
  /** 它下面直接挂着几个。0 就是叶子,折叠箭头不该出现。 */
  childCount: number;
  selected: boolean;
  collapsed: boolean;
  /** 它在一个藏起来的组里(不是自己藏的)。 */
  inherited: boolean;
  busy: boolean;
  dragging: boolean;
  drop: DropZone | undefined;
  onSelect: (id: string) => void;
  onFocusView: () => void;
  onToggleCollapse: (id: string) => void;
  onToggleHidden: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  const t = useI18n();
  const { attributes, listeners, setNodeRef: setDragRef } = useDraggable({ id: o.id });
  // 同一行两用:可拖,**也是落点**(dnd-kit 的 sortable 就是这么干的)。只可拖不可落的话,
  // `pointerWithin` 永远指不到任何一行 —— 屏幕上看着能拖,松手哪儿都不是落点。
  const { setNodeRef: setDropRef } = useDroppable({ id: o.id });
  // 两个 ref 合成一个:分开给同一节点写会互相盖掉。都是 dnd-kit 那边的稳定回调
  // (useNodeRef 里是 useCallback([])),所以这里也稳得住 —— 每次渲染换一个新函数的话,
  // 节点会被反复注销再注册。
  const attach = React.useCallback(
    (node: HTMLDivElement | null) => {
      setDragRef(node);
      setDropRef(node);
    },
    [setDragRef, setDropRef],
  );
  return (
    <div
      ref={attach}
      className="scene-object-row"
      // 淡显的是"实际看不见"的行,不只是自己藏了的:藏一个组,组里那些行也要
      // 看得出它们此刻不在画面里。`self` 与 `inherited` 分开,前者另加斜体 ——
      // 眼睛图标只说自己那一位,斜体说的是"是我自己藏的"。
      data-hidden={o.hidden ? "self" : inherited ? "inherited" : undefined}
      data-dragging={dragging || undefined}
      data-drop={drop}
      data-object-id={o.id}
      role="treeitem"
      aria-level={depth + 1}
      aria-expanded={childCount ? !collapsed : undefined}
      // 缩进只经过这一个值:行的左内距按它算(见 scenes.css 里那段)。
      style={{ "--depth": depth } as React.CSSProperties}
    >
      <button
        className="scene-object-name"
        //: dnd-kit 的那套属性(`role`、`tabIndex`、说明、`aria-pressed: undefined`)在前,
        //: 自己那两行在后 —— 顺序反过来 `aria-pressed` 会被它盖掉,选中态就读不出来了。
        {...attributes}
        {...listeners}
        aria-pressed={selected}
        onClick={() => onSelect(o.id)}
        onDoubleClick={onFocusView}
      >
        <ObjectKindIcon kind={o.kind} />
        <Truncate>{o.name}</Truncate>
        {childCount > 0 && collapsed && <small>{t("sceneChildCount").replace("{n}", String(childCount))}</small>}
      </button>
      {/* 折叠箭头放名字**右侧**(维护者:放左边会留一块看着怪异的内间距,行首直接从图标起)。
          没孩子的留一块同宽的空位,名字才对得齐。 */}
      {childCount ? (
        <IconButton
          unstyled
          className="scene-object-twist"
          label={t(collapsed ? "sceneExpandNamed" : "sceneCollapseNamed").replace("{name}", o.name)}
          onClick={() => onToggleCollapse(o.id)}
        >
          <ChevronRight
            size={13}
            style={{ transform: collapsed ? undefined : "rotate(90deg)" }}
          />
        </IconButton>
      ) : (
        <span className="scene-object-twist" />
      )}
      {/* 显示/隐藏和删除并排,同尺寸、同一种安静的样子 —— 此前藏一个物体要先选中它,
          再到下面的「调整对象」里找那颗眼睛;列表里只有一个「隐藏」字样的标记。 */}
      <IconButton
        unstyled
        className="scene-object-visibility"
        label={t(o.hidden ? "sceneShowObjectNamed" : "sceneHideObjectNamed").replace("{name}", o.name)}
        disabled={!!busy}
        onClick={() => onToggleHidden(o.id)}
      >
        {o.hidden ? <EyeOff size={14} /> : <Eye size={14} />}
      </IconButton>
      <IconButton
        unstyled
        className="scene-object-delete"
        label={t("sceneDeleteObjectNamed").replace("{name}", o.name)}
        disabled={!!busy}
        onClick={() => onRemove(o.id)}
      >
        <Trash2 size={14} />
      </IconButton>
    </div>
  );
}
