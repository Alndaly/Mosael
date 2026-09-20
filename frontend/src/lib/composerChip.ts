import type React from "react";

/**
 * 输入框上方那一排小条里的一条:一张图、一段文字、一篇笔记。
 *
 * 这个形状是**输入框和给它塞东西的那些人之间的约定**,所以住在 lib 里:笔记那边要造一条
 * 笔记小条,画板那边要造一条素材小条,而它们不该为了一个类型反过来 import 智能体
 * (features 之间互相 import,读的人就再也说不清谁依赖谁)。怎么显示仍然在
 * `features/agent/ComposerChips`。
 */
export interface ComposerChip {
  id: string;
  label: string;
  /** 有画面的给缩略图(图片、视频封面);没有的给图标。 */
  thumbnail?: string;
  icon: React.ReactNode;
  /** 自己处理的预览 —— 媒体交给全局灯箱,那里有翻页、Esc 和层级。 */
  onOpen?: () => void;
  /** 一段读一读的字(文本附件、笔记正文)。交给下面那个共用的只读弹层,不必各开一个。 */
  text?: { title: string; body: string };
  onRemove: () => void;
}
