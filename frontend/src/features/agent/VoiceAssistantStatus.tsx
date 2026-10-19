/**
 * 助手的「那一颗」:波形条 / 转圈 / 生成语音的进度环 / 失败的警示,全在这里。
 *
 * **为什么是一个组件而不是两处各画一遍。** 这颗东西出现在两个地方:浮在右下角的浮标,和原生视图
 * (内嵌浏览器、工作台画布)在前台时收进外壳顶栏的那一颗。此前两处各写一次 `<VoiceOrb>` ——
 * 新加的状态只要漏掉一处,那一处就退回「只有一个点点点」。收成一个组件之后,状态和画法只有一份。
 *
 * 状态说法在 `voiceAssistant.ts`(纯函数,两处共用);这里只负责**画**。
 */

import React from "react";

import { VoiceOrb } from "@/features/agent/VoiceOrb";
import type { VoiceLoopState } from "@/features/agent/useVoiceLoop";
import { cn } from "@/lib/utils";

export function VoiceAssistantStatus({
  state,
  levelRef,
  className,
}: {
  state: VoiceLoopState;
  /** 当前音量,1.0 = 开口阈值。见 useVoiceLoop。 */
  levelRef: React.MutableRefObject<number>;
  className?: string;
}) {
  return (
    <span
      data-voice-state={state}
      className={cn("pointer-events-none grid size-full place-items-center", className)}
    >
      <VoiceOrb state={state} levelRef={levelRef} />
    </span>
  );
}
