/**
 * 免提浮标的**状态说法**:同一份状态机,同一个说法,浮着的和收进顶栏的那一颗共用。
 *
 * 维护者报的是「智能体助手在音频生成过程中没有 loading 以及对应 UI —— 生成语音时没有任何状态变化」。
 * 补这一版时最容易犯的错,是**在两处各写一套**:浮标这边写「正在生成语音…」,顶栏那边写
 * 「合成中」,或者一处有重试、一处没有 —— 那正是维护者说的「不要每处各写一套」。
 *
 * 所以状态判断和文案**只在这一个函数里**,两处渲染点都读它:
 * - 顶部那颗浮标:短名做 aria-label,整句做旁边那一行可见说明;
 * - 收进外壳顶栏的那一颗:短名做 aria-label,整句做悬停说明(顶栏没有地方摆一句话)。
 *
 * 失败那一句要带上**原因**和**能不能重试**:没有音色的 409 是配置待办(重试一万次也还是那句),
 * 连不上 / 超时才是再来一次能好的。能不能重试只由 `speechFailure` 说了算,这里不猜。
 */

import type { MessageKey } from "@/app/messages";
import type { SpeechFailure } from "@/features/agent/agentSpeech";
import type { VoiceLoopState } from "@/features/agent/useVoiceLoop";

export interface VoiceAssistantView {
  /** 短名:按钮叫什么(读屏念的那一句)。 */
  label: string;
  /** 一整句:浮标旁边那一行,或者顶栏图标的悬停说明。 */
  caption: string;
  /** 这一次点击是**重试**,不是关掉免提。 */
  retry: boolean;
}

export function voiceAssistantView({
  on,
  state,
  heard,
  failure,
  t,
}: {
  on: boolean;
  state: VoiceLoopState;
  heard: string;
  failure: SpeechFailure | null;
  t: (key: MessageKey) => string;
}): VoiceAssistantView {
  if (!on) return { label: t("voiceModeStart"), caption: t("voiceModeStart"), retry: false };

  //: **生成语音中** —— 这一次修的洞。它不是「在说」:声音还没出来。
  if (state === "synthesizing")
    return { label: t("voiceMode_synthesizing"), caption: t("voiceMode_synthesizing"), retry: false };

  if (state === "synthesisFailed") {
    const reason = failure ? `:${failure.message}` : "";
    const retry = Boolean(failure?.retryable);
    return {
      label: t("voiceMode_synthesisFailed"),
      caption: `${t("voiceMode_synthesisFailed")}${reason}${retry ? ` · ${t("voiceDockRetry")}` : ""}`,
      retry,
    };
  }

  //: 转写用的是**转写那条既有文案**(编辑器的转写也用同一句),不塞进 voiceMode_* 那一组。
  const label = state === "transcribing" ? t("transcribing") : t(`voiceMode_${state}` as MessageKey);
  //: 听到的原话比状态更有信息量:听错的时候当场就看得见错在哪个字。
  const caption = state === "hearing" || !heard ? label : `${t("voiceDockHeard")}${heard}`;
  return { label, caption, retry: false };
}
