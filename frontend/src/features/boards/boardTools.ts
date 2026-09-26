import { Package, Sparkles, type LucideIcon } from "lucide-react";

import { isNodeProducer, type BoardProducerInfo } from "@/api/client";
import { kindIcon } from "@/features/boards/boardNodes";

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

export function boardToolIcon(group: string | undefined): LucideIcon {
  return GROUP_ICONS[group ?? ""] ?? kindIcon("action");
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
      icon: boardToolIcon(one.board_group),
      keywords: one.tool_name ? [one.tool_name] : undefined,
    }));
}
