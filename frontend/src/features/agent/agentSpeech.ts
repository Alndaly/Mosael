/**
 * 念一句话:把文字合成成音频。消息下的「念给我听」(SpeakButton)和免提(useVoiceLoop)共用。
 *
 * 走 `speakWithAgentVoice`(api/domains/speech,底下是 `apiBlob`)—— 和 `api()` 同一份请求实现:带 Accept-Language(没选音色那句 409 按界面语言
 * 说),掉线、401、报错正文都在那里处理。此前两处各手写一份 fetch:那句 409 永远是中文,掉线和
 * 登录失效也各有各的说法。
 */

import { toast } from "sonner";

import { ApiError, ApiOfflineError, speakWithAgentVoice } from "@/api/client";

/** 后端一次最多收这么多字(AgentSpeechRequest.text)。超出的念不了,也不该让整句报 422。 */
const MAX_SPEECH_CHARS = 4000;

export function synthesizeSpeech(text: string, workspaceId: string): Promise<Blob> {
  return speakWithAgentVoice({ text: text.slice(0, MAX_SPEECH_CHARS), workspace_id: workspaceId });
}

/**
 * 一次合成失败**是什么样**,不只是"说一句"。
 *
 * 浮标要的不止是一句话:它还得知道**能不能重试**。没有音色(409)是待办,不是故障 —— 重试一
 * 万次也还是那句「先去设置里选一个」;连不上、超时、播放器出错才是"再来一次"能好的。
 * 这个判断只写在这里,toast(`reportSpeechFailure`)和浮标的状态(`useVoiceLoop`)读同一份。
 */
export interface SpeechFailure {
  message: string;
  /** 再来一次有希望吗。没有音色的 409 是配置待办,重试解决不了。 */
  retryable: boolean;
}

export function speechFailure(error: unknown, fallback: string): SpeechFailure {
  if (error instanceof ApiError && error.status === 409) return { message: error.message, retryable: false };
  if (error instanceof ApiError || error instanceof ApiOfflineError) return { message: error.message, retryable: true };
  return { message: fallback, retryable: true };
}

/**
 * 念不出来时说一声。
 *
 * 409 = 还没选音色:那是个待办,不是故障 —— 用普通提示说清下一步在哪。服务端给了原因(或者
 * 连不上服务器)就说那个原因;别的失败(播放器出错之类)说 `fallback`。
 */
export function reportSpeechFailure(error: unknown, fallback: string): void {
  const { message, retryable } = speechFailure(error, fallback);
  if (retryable) toast.error(message);
  else toast.message(message);
}
