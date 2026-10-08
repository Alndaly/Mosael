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
 * 念不出来时说一声。
 *
 * 409 = 还没选音色:那是个待办,不是故障 —— 用普通提示说清下一步在哪。服务端给了原因(或者
 * 连不上服务器)就说那个原因;别的失败(播放器出错之类)说 `fallback`。
 */
export function reportSpeechFailure(error: unknown, fallback: string): void {
  if (error instanceof ApiError && error.status === 409) {
    toast.message(error.message);
    return;
  }
  toast.error(error instanceof ApiError || error instanceof ApiOfflineError ? error.message : fallback);
}
