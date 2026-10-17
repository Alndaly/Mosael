/**
 * 对话类才读的那个开关:「念回复时先出声」还是「等整段」。
 *
 * **只有对话类的消费者读它**(免提 / 消息喇叭)。文件类 —— 工作流「语音合成」节点、画板音配音、
 * 笔记「存成素材」—— 一个字都不读:那些产物是素材,一次拿完才算成功,不存在"先出声"这回事。
 *
 * 存的是服务端 `agent_voice_prefs.speak_early`(设置 → 智能体 → 语音对话)。读它要一次往返,
 * 而首句延迟正是这次要压的东西 —— 所以记住上一次的值:页面挂上就预取,真正开口时同步取缓存;
 * 设置页保存成功时把新值写回来,不用等下一次重新拉取。取不到(没登录 / 掉线)按默认「先出声」——
 * 那是更接近用户点「念给我听」时预期的一边,而且不改任何文件类的行为。
 */

import { getAgentVoice } from "@/api/client";

export type SpeechMode = "early" | "whole";

/** 30 秒后重取一次:另一台设备改了设置,这台最多半分钟后跟上。 */
const FRESH_MS = 30_000;

let cached: SpeechMode | null = null;
let cachedAt = 0;
let inflight: Promise<SpeechMode> | null = null;

type AgentVoicePreference = { speak_early?: boolean };

export function speechModeOf(preference: AgentVoicePreference): SpeechMode {
  //: 老服务端没有这一格(或它默认 true)时是「先出声」。
  return preference.speak_early === false ? "whole" : "early";
}

/** 设置页保存成功 / 水合时写回,下一次开口不必等一次往返。 */
export function rememberSpeechMode(mode: SpeechMode): void {
  cached = mode;
  cachedAt = Date.now();
}

function fetchSpeechMode(): Promise<SpeechMode> {
  if (inflight) return inflight;
  let request: Promise<SpeechMode>;
  request = getAgentVoice()
    .then((preference) => {
      const mode = speechModeOf(preference);
      cached = mode;
      cachedAt = Date.now();
      return mode;
    })
    .catch(() => cached ?? "early")
    .finally(() => {
      if (inflight === request) inflight = null;
    });
  inflight = request;
  return request;
}

/** 页面挂上就取一次(不阻塞任何东西);已经有了就不重复取。 */
export function prefetchSpeechMode(): void {
  if (cached && Date.now() - cachedAt < FRESH_MS) return;
  void fetchSpeechMode();
}

/** 真正要念之前取这份设置:有缓存就同步回来,没有才等一次往返。 */
export async function loadSpeechMode(): Promise<SpeechMode> {
  if (cached) {
    if (Date.now() - cachedAt >= FRESH_MS) prefetchSpeechMode();
    return cached;
  }
  return fetchSpeechMode();
}

/** 测试用:清掉记住的那一份,免得用例之间互相影响。 */
export function resetSpeechModeForTests(): void {
  cached = null;
  cachedAt = 0;
  inflight = null;
}
