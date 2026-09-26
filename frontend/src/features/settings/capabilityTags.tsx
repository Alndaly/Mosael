import { AudioLines, ImageIcon, MessageSquare, Mic, Speech, Video, type LucideIcon } from "lucide-react";

import type { MessageKey } from "@/app/messages";

/**
 * 模型能力标签的样子:短名 + 图标。**图标和设置侧栏里那几个能力分区是同一套**(对话 / 绘图 / 视频 / 音频),
 * 在模型行上看见一枚图像标签,和左边「AI 绘图」那一项是一眼能对上的同一件事。
 *
 * 模型行上和模型设置里各画一遍,规则放在这里 —— 分开写的那一版,行上是原样的 `image`,弹窗里是另一套字。
 */
export const CAPABILITY_TAGS: Record<string, { label: MessageKey; icon: LucideIcon }> = {
  chat: { label: "capTagChat", icon: MessageSquare },
  image: { label: "capTagImage", icon: ImageIcon },
  video: { label: "capTagVideo", icon: Video },
  audio: { label: "capTagAudio", icon: AudioLines },
  tts: { label: "capTagTts", icon: Speech },
  podcast: { label: "capTagPodcast", icon: Mic },
};

/** 标签的显示顺序:对话在前,生成随后,和设置侧栏的分区同序。认不出的能力 id 排在最后、原样显示。 */
export function orderedCapabilities(ids: readonly string[]): string[] {
  const order = Object.keys(CAPABILITY_TAGS);
  const rank = (id: string) => (order.includes(id) ? order.indexOf(id) : order.length);
  return [...new Set(ids)].sort((a, b) => rank(a) - rank(b));
}
