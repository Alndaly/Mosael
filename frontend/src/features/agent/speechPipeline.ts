/**
 * 对话类的组合层:按句取、边取边播。**切分只发生在这里,共用核心不动。**
 *
 *      synthesize(text) → 完整音频字节          ← 唯一的原始能力(agentSpeech.synthesizeSpeech)
 *        ├─ 文件类:一次拿完                    ← 工作流节点 / 画板音配音 / 笔记「存成素材」
 *        └─ 对话类:这段(`speakText`)           ← 免提、消息喇叭、笔记朗读
 *
 * 规矩:
 * - 第一句合成完**立刻播**,播的同时去取下一句(不是等全部合成完);
 * - `cancelled()` 说这次开念已经作废(teardown / 打断 / 另一段接管)时,在途的合成**不再播**,
 *   后面的句子**不再取**;
 * - 任何一句合成或播放失败都交给 `onFailure`(调用方用既有文案说清),**不静默停在半句**;
 *   已经播完的句子就那么结束了,下一句不再开始;
 * - `whole` 是设置「等整段」:一次取完 —— 行为和加流水线之前完全一致。**单句 / 很短的话也走一次取完**
 *   (同一份输出,只是不走队列,这是实现优化,不是另一条语义)。
 */

import { splitSpeech } from "@/lib/speechText";

export type SpeechOutcome = "done" | "cancelled" | "failed";

/** 短到不值得排队的回复(字符数):合成一次反而更快,听感也和整段一致。 */
export const SHORT_TEXT_CHARS = 12;

/** `playBlob` 的三种收尾:正常播完 / 被别的播放接管或 stopPlayback 掐掉 / 播放器出错。 */
export type PlaybackResult = "played" | "interrupted" | "failed" | void;

export interface SpeakTextOptions {
  text: string;
  /** 唯一的原始能力:一段文字 → 一段完整音频。 */
  synthesize: (text: string) => Promise<Blob>;
  /** 播一段;正常播完才落定。`interrupted` / `failed` 要如实交回来。 */
  play: (blob: Blob) => Promise<PlaybackResult>;
  /** 设置「等整段」。默认「先出声」。 */
  whole?: boolean;
  /** 这次开念作废了吗(teardown / 打断 / 另一段接管)。 */
  cancelled?: () => boolean;
  /** 合成或播放失败时说清;调用方传既有文案的 reportSpeechFailure。 */
  onFailure?: (error: unknown) => void;
  /** 第一段音频要出声了(界面据此从「准备中」切到「在念」)。 */
  onFirstAudio?: () => void;
}

type Fetched = { ok: true; blob: Blob } | { ok: false; error: unknown };

const playbackFailed = new Error("audio playback failed");

export async function speakText(options: SpeakTextOptions): Promise<SpeechOutcome> {
  const {
    text,
    synthesize,
    play,
    whole = false,
    cancelled = () => false,
    onFailure,
    onFirstAudio,
  } = options;
  if (!text.trim()) return "done";

  const chunks = splitSpeech(text);
  if (!chunks.length) return "done";
  //: 很短的两三句合成一次反而更快(少一次往返、少一个接缝),听感也和整段一致。
  const singleShot = whole || chunks.length === 1 || text.trim().length <= SHORT_TEXT_CHARS;

  //: **立刻**接住失败:下一句的合成在上一句还播着的时候就发出去了,不接的话一个失败会变成
  //: 未处理的 rejection,而这里要的是"播完这一句,再说第二句为什么没念"。
  const fetchChunk = (sentence: string): Promise<Fetched> =>
    synthesize(sentence).then(
      (blob) => ({ ok: true, blob }),
      (error: unknown) => ({ ok: false, error }),
    );

  const playChunk = async (blob: Blob): Promise<SpeechOutcome> => {
    if (cancelled()) return "cancelled";
    onFirstAudio?.();
    const result = await play(blob);
    if (cancelled() || result === "interrupted") return "cancelled";
    if (result === "failed") throw playbackFailed;
    return "done";
  };

  try {
    if (singleShot) {
      const fetched = await fetchChunk(text.trim());
      if (cancelled()) return "cancelled";
      if (!fetched.ok) throw fetched.error;
      return await playChunk(fetched.blob);
    }

    let next = fetchChunk(chunks[0].text);
    for (let index = 0; index < chunks.length; index += 1) {
      const fetched = await next;
      if (cancelled()) return "cancelled";
      if (!fetched.ok) throw fetched.error;
      //: 这一段已经拿到:现在就去取下一段,和播放同时进行。
      if (index + 1 < chunks.length) next = fetchChunk(chunks[index + 1].text);
      const outcome = await playChunk(fetched.blob);
      if (outcome !== "done") return outcome;
      const gap = chunks[index].gapAfterMs;
      if (gap > 0 && index + 1 < chunks.length) {
        await new Promise((resolve) => setTimeout(resolve, gap));
        if (cancelled()) return "cancelled";
      }
    }
    return "done";
  } catch (error) {
    if (cancelled()) return "cancelled";
    onFailure?.(error);
    return "failed";
  }
}
