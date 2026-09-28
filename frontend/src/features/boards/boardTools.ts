import { Box, FolderOpen, Sparkles, Package, Wrench, type LucideIcon } from "lucide-react";

import type { BoardItem, BoardProducerInfo, BoardRunForms } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { kindIcon, kindText } from "@/features/boards/boardNodes";
import { nodeTypeIcon } from "@/features/nodeForms/nodeIcons";

/**
 * 画板上的**能力**:把内容变成新内容的工具住在内容格上(ADR 0025 修订「能力住在内容格上」)—— 音频格会转写、
 * 分离人声、降噪,视频格会转 GIF,便签会翻译,插件工具按它吃什么内容挂在那几种格子上。选中一格,操作条上一排
 * 图标就是它的能力;点一下,它的面板挂在格子下面。**挂在哪由后端说**(`role` / `hosts`,见后端 boards.transforms
 * 的 board_role / board_hosts),这里不另写一张「什么格子会什么」的表。
 */

/** 按吃什么内容归的组(后端 `board_group`)的图标:吃什么内容就用那种格子的图标;凭空产出的用「生成」那颗。 */
const GROUP_ICONS: Record<string, LucideIcon> = {
  new: Sparkles,
  image: kindIcon("image"),
  video: kindIcon("video"),
  audio: kindIcon("audio"),
  text: kindIcon("note"),
  scene: kindIcon("scene"),
  entity: kindIcon("entity"),
  asset: Package,
};

/**
 * 一项能力(或一个生成器)的图标。**操作条上那一枚、「更多」菜单里那一行、面板的名字读的都是它。**
 *
 * 先认节点类型(内置节点在工作流画布上是什么图标,在画板上就是什么 —— 同一份 nodeIcons),
 * 认不出的(插件工具:插件的 node 块不声明图标)按它吃什么内容的那一组;组也没见过的是一把扳手。
 * 不在这里按工具名另写一张表。
 */
export function boardToolIcon(tool: Pick<BoardProducerInfo, "type" | "board_group"> | undefined): LucideIcon {
  return nodeTypeIcon(tool?.type) ?? GROUP_ICONS[tool?.board_group ?? ""] ?? Wrench;
}

/** 句末:中文的。!?,英文的句点后面跟空白(`v1.5` 里的点不算)—— 和后端 boards.transforms 同一种切法。 */
const SENTENCE_END = /(?<=[。！？!?])|(?<=\.)\s/u;

/** 一段说明的**第一句**,去掉 markdown 记号(`**交回的是地址**` 不该把两颗星号印在界面上)。 */
export function firstSentence(text: string): string {
  return (toPlainText(text).split(SENTENCE_END)[0] ?? "").trim();
}

/**
 * 这一格**有没有内容可给**:便签要有字,文档要挑了笔记,3D 场景格引用着场景,媒体格要有素材。
 * 能力吃的就是这一样 —— 没有的话操作条上不列能力(后端同样拒:boardErr_abilityNeedsContent)。
 */
export function hostHasContent(item: BoardItem): boolean {
  if (item.kind === "note") return Boolean(item.text?.trim());
  if (item.kind === "document") return Boolean(item.note_id);
  if (item.kind === "scene") return Boolean(item.scene_id);
  //: 资产格给的是它引用的资产(补全多角度、生成表情吃的就是它,ADR 0027 阶段 4)。
  if (item.kind === "entity") return Boolean(item.entity_id);
  if (item.kind === "frame") return false;
  return Boolean(item.asset_id);
}

/**
 * 这一格的能力:`role` 是能力、挂得在这种格子上的那几个,按后端的顺序(内置的在前,插件工具在后)。
 *
 * **资产格不是一个样子**:人物、场景、道具各有各的能力(「生成表情」只有人物有,后端 `host_entity_kinds`)。
 * `entityKind` 是资产格引用的那个资产的种类;还不知道(没取到)时,只点名了种类的那几项先不列。
 */
export function boardAbilities(
  item: BoardItem,
  producers: BoardProducerInfo[] | undefined,
  entityKind?: string,
): BoardProducerInfo[] {
  if (!producers || !hostHasContent(item)) return [];
  return producers.filter(
    (one) =>
      one.role === "ability" &&
      one.hosts.includes(item.kind) &&
      (item.kind !== "entity" || !one.host_entity_kinds?.length || (entityKind !== undefined && one.host_entity_kinds.includes(entityKind))),
  );
}

/** 3D 场景格「按剧本搭」的产出者(工作流节点 scene_from_text,后端 boards.transforms 判成场景格的一种填法)。 */
export const SCENE_FROM_TEXT = "node:scene_from_text" as const;

/** 操作条上直接摆几项能力;其余收进「⋯」。内置的排在前面,所以常用的那几项总在外面。 */
export const DIRECT_ABILITIES = 4;

/** 「添加」里的一行:放一格什么(`value` 是 BoardsView 认的那个动作)、在哪一组。 */
export interface BoardAddOption {
  value: string;
  label: string;
  description: string;
  group: string;
  icon: LucideIcon;
}

/**
 * 「添加」的三组(ADR 0025 决定 6,2026-09-28 修订):组名是动词,行是名词。
 *
 * - **新建**:放一格空的,让 AI 生成 / 写,或者自己挑、自己写(图片、视频、音频、便签、文档);
 * - **从库里放**:挑一个现成的放上来(素材库的素材、资产库的资产、3D 场景);
 * - **整理**:不产出内容的(分组)。
 *
 * 此前是「生成 / 从素材库 / 引用 / 整理」四组 11 行:「生成」和「从素材库」是同样的三种格子列了两遍,便签在
 * 「整理」里(它会让 AI 写,是内容格),文档在「引用」里(空文档格也能让 AI 写一篇)。
 */
type AddGroup = "create" | "library" | "organize";

const GROUP_LABELS: Record<AddGroup, MessageKey> = {
  create: "boardsGroupCreate",
  library: "boardsGroupFromLibrary",
  organize: "boardsGroupOrganize",
};

/** 「添加」里格子那一段的一行。 */
interface KindRow {
  value: string;
  kind: BoardItem["kind"];
  group: AddGroup;
  /** 「素材」那一行有自己的名字、说明和图标(素材库);其余就是那种格子的(kindText、kindIcon)。 */
  text?: { label: MessageKey; hint: MessageKey; icon: LucideIcon };
}

//: **同一组的必须挨在一起。** SearchableSelect 按*相邻*的同名 group 归组(它不重排),隔开写就会渲染出
//: 第二个同名小标题。
const KIND_ROWS: KindRow[] = [
  { value: "image", kind: "image", group: "create" },
  { value: "video", kind: "video", group: "create" },
  { value: "audio", kind: "audio", group: "create" },
  { value: "note", kind: "note", group: "create" },
  { value: "document", kind: "document", group: "create" },
  //: 一格空的 3D 场景,连一段剧本进来按剧本搭(「从库里放」那一行是挑一个现成的)。
  { value: "scene-new", kind: "scene", group: "create", text: { label: "boardKindScene", hint: "boardsNewSceneHint", icon: Box } },
  //: 一格时间线(ADR 0030):放下时先建好它那条时间线,把视频、图片、音频连进来就是接到末尾。
  { value: "sequence-new", kind: "sequence", group: "create" },
  //: 一行挑三种:弹窗里按图片 / 视频 / 音频筛,挑中哪一种放哪一种格子(AssetPickerDialog 的 `media`)。
  { value: "pick-media", kind: "image", group: "library", text: { label: "boardsAddMedia", hint: "boardsAddMediaHint", icon: FolderOpen } },
  //: 资产库里的人物 / 场景 / 道具(ADR 0027):先挑再放,和 3D 场景一样。
  { value: "entity", kind: "entity", group: "library" },
  { value: "scene", kind: "scene", group: "library" },
  { value: "frame", kind: "frame", group: "organize" },
];

/**
 * 工具条「添加」的整张单子:**只有格子**,按动词分成新建 / 从库里放 / 整理三组(ADR 0025 决定 6)。
 *
 * 没有「工具」那一组:画板上没有单独的工具格,把内容变成新内容的事是内容格自己的能力 —— 放一段音频进来,
 * 选中它,操作条上就有转写、分离、降噪。每一行都是同一个样子:图标、名字、一句说明;格子的说明和拉线菜单读的是
 * 同一份(kindText)。
 */
export function boardAddCatalog(t: (key: MessageKey) => string): BoardAddOption[] {
  return KIND_ROWS.map(({ value, kind, group, text }) => {
    const { label, hint } = text ? { label: t(text.label), hint: t(text.hint) } : kindText(t, kind);
    return { value, label, description: hint, group: t(GROUP_LABELS[group]), icon: text?.icon ?? kindIcon(kind) };
  });
}

type Bindings = BoardRunForms["node"]["bindings"];

/** 产出者清单里一个字段的声明里,默认绑定要读的那几样(节点声明 + 画板多给的 `board_sources`)。 */
interface ToolFieldSpec {
  required?: boolean;
  /** 能接哪几种上游格子(后端 boards.tools.bindable_kinds)。 */
  board_sources?: string[];
}

/**
 * 上游这一格**能不能给出值**。还没有产出的空槽(图片还在生成、文档还没挑)接上去也取不到东西 ——
 * 服务端运行时照样会跳过它,面板就不把它列成一个可以点的选项。
 */
export function givesValue(item: BoardItem): boolean {
  if (item.kind === "note") return true;
  if (item.kind === "document") return Boolean(item.note_id);
  if (item.kind === "scene") return Boolean(item.scene_id);
  if (item.kind === "entity") return Boolean(item.entity_id);
  return Boolean(item.asset_id);
}

/**
 * 上游这一格**此刻**给出的值 —— 和服务端 boards.tools._value_of 同一张表:场景给场景 id、媒体给素材 id、
 * 便签给字。文档的正文要按钉住的版本去读,这里说不出,给空串。依赖它的字段(镜头跟着场景)拿它查清单。
 */
export function sourceValue(item: BoardItem): string {
  if (item.kind === "scene") return item.scene_id ?? "";
  if (item.kind === "entity") return item.entity_id ?? "";
  if (item.kind === "note") return item.text ?? "";
  if (item.kind === "document") return "";
  return item.asset_id ?? "";
}

/**
 * 连进来的上游 → 接到哪些字段的默认绑定:**必填**、能接上游、还没绑也没手填过的字段,绑第一个接得上的上游。
 *
 * 「没手填过」看的是 config 里有没有这个键 —— 用户把它切回「手填」时,面板会把它写成空串
 * (见 AbilityComposer 的 unbind),于是不会刚解开就又被绑回去。返回 null 表示不用改。
 */
export function defaultBindings(
  specs: Record<string, ToolFieldSpec>,
  config: Record<string, unknown>,
  bindings: Bindings,
  sources: BoardItem[],
): Bindings | null {
  let next: Bindings | null = null;
  for (const [key, spec] of Object.entries(specs)) {
    if (!spec?.required || !spec.board_sources?.length) continue;
    if (bindings[key]?.length || key in config) continue;
    const first = sources.find((one) => spec.board_sources?.includes(one.kind) && givesValue(one));
    if (!first) continue;
    next = { ...(next ?? bindings), [key]: [{ from: first.id }] };
  }
  return next;
}
