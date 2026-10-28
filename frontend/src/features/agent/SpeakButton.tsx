/**
 * 把一段文字念出来。消息页脚上那个喇叭。
 *
 * **同一条路要服务三件事**:这里的播放、确认卡与提问的语音化、失败出声。对用户来说它们
 * 是同一个声音,所以音色配置只有一份(设置里的「语音对话」),端点也只有一个
 * (`POST /api/agent/speech`,不产出素材 —— 见那边的说明)。
 *
 * 几个刻意的选择:
 *
 * · **同一时刻只响一个。** 连点两条消息,两段语音叠在一起是听不清的;后点的接管,前一段停掉。
 * · **再点一下就停。** 念到一半发现不是想听的那条,总得能掐掉 —— 这也是后面"打断"要用的同一个开关。
 * · **没配音色不是错误。** 回 409 时给一句"去设置里选一个",而不是一个红色的失败。
 * · **按句流水线**:第一句合成完就播,后面边播边取 —— 但只在设置「念回复时先出声」时这样;
 *   选了「等整段」就一次取完,和加流水线之前一模一样。**文件类的几个入口不读这个设置。**
 */

import React from "react";
import { Loader2, Square, Volume2 } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { playBlob, stopPlayback } from "@/lib/audioPlayback";
import { reportSpeechFailure, synthesizeSpeech } from "@/features/agent/agentSpeech";
import { speakText } from "@/features/agent/speechPipeline";
import { loadSpeechMode, prefetchSpeechMode } from "@/features/agent/speechSettings";
import { FOOTER_ACTION_CLASS } from "@/features/agent/agentRow";
import { cn } from "@/lib/utils";

export function SpeakButton({
  text,
  workspaceId,
  className,
}: {
  text: string;
  workspaceId?: string;
  className?: string;
}) {
  const t = useI18n();
  const [state, setState] = React.useState<"idle" | "loading" | "playing">("idle");
  //: 这一遍开念的代号。打断、卸载、另点一条都会让它加一 —— 在途的合成据此作废、不再播。
  const run = React.useRef(0);
  const reset = React.useCallback(() => setState("idle"), []);

  React.useEffect(() => {
    //: 页面挂上就取一次「先出声 / 等整段」,别等到点击才多一次往返。
    prefetchSpeechMode();
    // 组件没了(切会话、清空对话)声音也该停 —— 否则它会继续念一条已经不在屏幕上的消息。
    return () => {
      run.current += 1;
      if (stateRef.current !== "idle") stopPlayback();
    };
  }, []);

  const stateRef = React.useRef(state);
  stateRef.current = state;

  const stop = React.useCallback(() => {
    run.current += 1;
    stopPlayback();
    reset();
  }, [reset]);

  async function play() {
    stopPlayback();
    const mine = (run.current += 1);
    setState("loading");
    const whole = (await loadSpeechMode()) === "whole";
    if (run.current !== mine) return;
    await speakText({
      text,
      //: 唯一的原始能力,一句一句地交给它 —— 切分在组合层,这个函数本身不认识"句子"。
      synthesize: (one) => synthesizeSpeech(one, workspaceId ?? ""),
      play: playBlob,
      whole,
      cancelled: () => run.current !== mine,
      onFirstAudio: () => {
        if (run.current === mine) setState("playing");
      },
      onFailure: (error) => reportSpeechFailure(error, t("speakFailed")),
    });
    if (run.current === mine) reset();
  }

  const busy = state === "loading";
  const active = state === "playing";
  return (
    // 和「复制」同一套外形(FOOTER_ACTION_CLASS):图标 11px、带文字、同样的圆角与内边距。
    // 并排的两个动作长得不一样时,读起来像两个不同来处的东西。
    <button
      type="button"
      className={cn(FOOTER_ACTION_CLASS, className)}
      aria-label={active ? t("speakStop") : t("speak")}
      disabled={busy || !text.trim()}
      onClick={() => (active ? stop() : void play())}
    >
      {busy ? (
        <Loader2 size={11} className="animate-mosael-spin" />
      ) : active ? (
        <Square size={11} className="fill-current" />
      ) : (
        <Volume2 size={11} />
      )}
      {active ? t("speakStopLabel") : t("speakLabel")}
    </button>
  );
}
