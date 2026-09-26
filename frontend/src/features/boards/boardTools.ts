import { Package, Sparkles, type LucideIcon } from "lucide-react";

import { isNodeProducer, type BoardItem, type BoardProducerInfo, type BoardRunForms } from "@/api/client";
import { DEFAULT_SIZE, kindIcon, type BoardToolFace, type ToolCellKind } from "@/features/boards/boardNodes";
import { isWorkflowFieldActive } from "@/features/nodeForms/fieldActivation";
import { nodeTypeIcon } from "@/features/nodeForms/nodeIcons";

/**
 * 画板上「添加 → 工具」和拉线菜单里的工具:**按它对内容做什么分组**,不照搬工作流的节点面板。
 *
 * 工作流面板按「流程 / AI / 音频 / 数据」分,那是搭流程的人的分法;画板上的人手里拿着一张图、一段视频、
 * 一张便签,问的是「这东西接下来能变成什么」。所以分组是后端按工具**吃什么内容**给的(`board_group`:
 * 处理图片 / 视频 / 音频 / 文字 / 3D 场景 / 素材,凭空产出素材的归「产出新素材」,见后端
 * boards/transforms.py),顺序也是后端排好的(同组挨在一起 —— 菜单按相邻的同名组归组);
 * 说明是给创作者看的那一句(`board_description`),不是写给搭流程的人、带 `{{…}}` 的节点说明。
 * 这里只把它们配上图标,不再分一次组、不另写一张表。
 */
export interface BoardToolOption {
  value: string;
  label: string;
  description: string;
  group: string;
  icon: LucideIcon;
  keywords?: string[];
}

/** 每一组的图标:吃什么内容就用那种格子的图标;凭空产出的用「生成」那颗。 */
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
 * 一个工具的图标。**菜单里那一行、画布上的工具格、格子上方那一行名字读的都是它。**
 *
 * 先认节点类型(内置节点在工作流画布上是什么图标,在画板上就是什么 —— 同一份 nodeIcons),
 * 认不出的(插件工具:插件的 node 块不声明图标)按它吃什么内容的那一组;组也没见过的是工具格的通用图标。
 * 不在这里按工具名另写一张表。
 */
export function boardToolIcon(tool: Pick<BoardProducerInfo, "type" | "board_group"> | undefined): LucideIcon {
  return nodeTypeIcon(tool?.type) ?? GROUP_ICONS[tool?.board_group ?? ""] ?? kindIcon("action");
}

/** 这个人能放上画板的工具(内置的四个挂在各自的格子上,不在这里)。 */
export function boardToolOptions(producers: BoardProducerInfo[]): BoardToolOption[] {
  return producers
    .filter((one) => isNodeProducer(one.id))
    .map((one) => ({
      value: one.id,
      label: one.label,
      // 同名工具可能来自不同插件(两个平台的 fetch_one_video),副标题点名是谁提供的。
      description: one.plugin_name ? `${one.plugin_name} · ${one.board_description ?? ""}` : (one.board_description ?? ""),
      group: one.board_group_label || one.board_group || "",
      icon: boardToolIcon(one),
      keywords: one.tool_name ? [one.tool_name] : undefined,
    }));
}

type Bindings = BoardRunForms["node"]["bindings"];

/** 工具清单里一个字段的声明里,工具格要读的那几样(节点声明 + 画板多给的 `board_sources`)。 */
interface ToolFieldSpec {
  label?: string;
  required?: boolean;
  advanced?: boolean;
  default?: unknown;
  options?: string[];
  option_labels?: Record<string, string>;
  options_from?: string;
  active_when?: Record<string, unknown | unknown[]>;
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
 * 一格上游 → 接到哪些字段的默认绑定:**必填**、能接上游、还没绑也没手填过的字段,绑第一个接得上的上游。
 *
 * 「没手填过」看的是 config 里有没有这个键 —— 用户把它切回「手填」时,面板会把它写成空串
 * (见 ActionComposer 的 setBound),于是不会刚解开就又被绑回去。返回 null 表示不用改。
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

function filledText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

/**
 * 工具格画成哪一种内容的空格子:它跑一次**主要**产出的那一种(后端 `output_kinds` 的第一个,ADR 0025)。
 * 文字落成便签;说不清是哪种素材(`asset`)的按最通用的媒体格 —— 图片。不按工具名猜。
 */
export function toolCellKind(tool: Pick<BoardProducerInfo, "output_kinds"> | null | undefined): ToolCellKind {
  const first = tool?.output_kinds?.[0];
  return first === "note" || first === "video" || first === "audio" ? first : "image";
}

/** 放下一格这个工具时它多大:和它长得像的那种内容格一样大(清单没到、查不到时是工具格的缺省)。 */
export function toolCellSize(tool: Pick<BoardProducerInfo, "output_kinds"> | null | undefined): { width: number; height: number } {
  return tool ? DEFAULT_SIZE[toolCellKind(tool)] : DEFAULT_SIZE.action;
}

/**
 * 工具格上要画的那几样,全从工具声明和这一格自己的表单里读 —— 不为哪个工具单写:
 *
 *  · **长成什么**:主产出的那种内容格(toolCellKind)。
 *  · **还差什么**:第一个**必填**、能接上游(`board_sources`)、此刻参与的字段,既没接上(绑定的,或跑的
 *    时候会默认接上的第一个合适的上游,和面板同一条 defaultBindings)也没手填 —— 格子上说「接视频」。
 *    至多这一句;选填的、设置项都不上格子(它们在面板里)。
 */
export function boardToolFace(tool: BoardProducerInfo, item: BoardItem, sources: BoardItem[]): BoardToolFace {
  const specs = (tool.config ?? {}) as Record<string, ToolFieldSpec>;
  const config = item.form?.config ?? {};
  const saved = item.form?.bindings ?? {};
  const bindings = defaultBindings(specs, config, saved, sources) ?? saved;
  const present = new Set(sources.map((one) => one.id));
  const lacking = Object.entries(specs).find(
    ([key, spec]) =>
      spec?.required &&
      spec.board_sources?.length &&
      isWorkflowFieldActive(spec, config, specs) &&
      !(bindings[key] ?? []).some((one) => present.has(one.from)) &&
      !filledText(config[key]),
  );
  return {
    label: tool.label,
    description: tool.board_description ?? "",
    plugin: tool.plugin_name,
    icon: boardToolIcon(tool),
    kind: toolCellKind(tool),
    missing: lacking ? ((lacking[1].board_sources ?? []) as BoardItem["kind"][]) : null,
  };
}
