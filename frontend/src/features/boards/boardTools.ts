import { Sparkles, Package, Wrench, type LucideIcon } from "lucide-react";

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
  if (item.kind === "frame") return false;
  return Boolean(item.asset_id);
}

/** 这一格的能力:`role` 是能力、挂得在这种格子上的那几个,按后端的顺序(内置的在前,插件工具在后)。 */
export function boardAbilities(item: BoardItem, producers: BoardProducerInfo[] | undefined): BoardProducerInfo[] {
  if (!producers || !hostHasContent(item)) return [];
  return producers.filter((one) => one.role === "ability" && one.hosts.includes(item.kind));
}

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

/** 「添加」的四组(ADR 0025 决定 6):组名是动词,行是名词。 */
type AddGroup = "generate" | "library" | "reference" | "organize";

const GROUP_LABELS: Record<AddGroup, MessageKey> = {
  generate: "boardsGroupGenerate",
  library: "boardsGroupFromLibrary",
  reference: "boardsGroupReference",
  organize: "boardsGroupOrganize",
};

/** 「添加」里格子那一段的一行。 */
interface KindRow {
  value: string;
  kind: BoardItem["kind"];
  group: AddGroup;
  /** 从素材库挑一份的那几行有自己的名字和说明;其余就是那种格子的名字和说明(kindText)。 */
  text?: { label: MessageKey; hint: MessageKey };
}

//: **同一组的必须挨在一起。** SearchableSelect 按*相邻*的同名 group 归组(它不重排),隔开写就会渲染出
//: 第二个同名小标题。
const KIND_ROWS: KindRow[] = [
  { value: "image", kind: "image", group: "generate" },
  { value: "video", kind: "video", group: "generate" },
  { value: "audio", kind: "audio", group: "generate" },
  { value: "pick-image", kind: "image", group: "library", text: { label: "boardsPickImage", hint: "boardsPickImageHint" } },
  { value: "pick-video", kind: "video", group: "library", text: { label: "boardsPickVideo", hint: "boardsPickVideoHint" } },
  { value: "pick-audio", kind: "audio", group: "library", text: { label: "boardsPickAudio", hint: "boardsPickAudioHint" } },
  { value: "document", kind: "document", group: "reference" },
  { value: "scene", kind: "scene", group: "reference" },
  { value: "note", kind: "note", group: "organize" },
  { value: "frame", kind: "frame", group: "organize" },
];

/**
 * 工具条「添加」的整张单子:**只有格子**,按动词分成生成 / 从素材库 / 引用 / 整理四组(ADR 0025 决定 6)。
 *
 * 没有「工具」那一组:画板上没有单独的工具格,把内容变成新内容的事是内容格自己的能力 —— 放一段音频进来,
 * 选中它,操作条上就有转写、分离、降噪。每一行都是同一个样子:图标、名字、一句说明;格子的说明和拉线菜单读的是
 * 同一份(kindText)。
 */
export function boardAddCatalog(t: (key: MessageKey) => string): BoardAddOption[] {
  return KIND_ROWS.map(({ value, kind, group, text }) => {
    const { label, hint } = text ? { label: t(text.label), hint: t(text.hint) } : kindText(t, kind);
    return { value, label, description: hint, group: t(GROUP_LABELS[group]), icon: kindIcon(kind) };
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
  return Boolean(item.asset_id);
}

/**
 * 上游这一格**此刻**给出的值 —— 和服务端 boards.tools._value_of 同一张表:场景给场景 id、媒体给素材 id、
 * 便签给字。文档的正文要按钉住的版本去读,这里说不出,给空串。依赖它的字段(镜头跟着场景)拿它查清单。
 */
export function sourceValue(item: BoardItem): string {
  if (item.kind === "scene") return item.scene_id ?? "";
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
