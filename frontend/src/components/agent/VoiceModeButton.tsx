/**
 * 免提对话的开关。开着的时候麦克风一直听,说完一句自动发,它答完念给你听。
 *
 * 和「说话输入」是两个东西,所以是两个按钮:说话输入是**把话填进输入框**,你还要看一眼、
 * 改一改、再按发送;免提是**直接发出去**。把它们做成一个按钮的两种模式,等于让人每次都要
 * 先确认自己现在处在哪一种 —— 而这两种的后果差别很大(一个可撤回,一个已经发出去了)。
 *
 * 状态直接画在按钮上:听 / 在听你说 / 在想 / 在念。语音模式下用户多半没盯着屏幕,但当他
 * 看过来时,得一眼知道现在轮到谁 —— 一个只会转圈的按钮回答不了这个问题。
 */

import React from "react";
import { Ear, Loader2, Mic, Volume2 } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { useVoiceLoop, type VoiceLoopState } from "@/components/agent/useVoiceLoop";
import { cn } from "@/lib/utils";

const ICONS: Record<Exclude<VoiceLoopState, "off">, React.ComponentType<{ size?: number; className?: string }>> = {
  listening: Ear,
  hearing: Mic,
  thinking: Loader2,
  speaking: Volume2,
};

export function VoiceModeButton(props: {
  workspaceId: string;
  onUtterance: (text: string) => Promise<void> | void;
  reply: string;
  busy: boolean;
  question?: { question: string; options: string[] } | null;
  onAnswer?: (index: number) => Promise<void> | void;
  pendingConfirmations?: string[];
  failure?: string;
}) {
  const t = useI18n();
  const loop = useVoiceLoop(props);
  const Icon = loop.state === "off" ? Mic : ICONS[loop.state];
  const label = loop.state === "off" ? t("voiceModeStart") : t(`voiceMode_${loop.state}` as "voiceMode_listening");

  return (
    <Button
      variant="ghost"
      size={loop.on ? "sm" : "icon"}
      className={cn("rounded-full", loop.on && "gap-1.5 px-2.5 text-primary")}
      aria-label={label}
      title={label}
      onClick={() => (loop.on ? loop.stop() : void loop.start())}
    >
      <Icon size={15} className={loop.state === "thinking" ? "animate-mosael-spin" : undefined} />
      {loop.on && <span className="text-ui-xs">{label}</span>}
    </Button>
  );
}
