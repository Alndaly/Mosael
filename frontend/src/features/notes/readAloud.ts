import React from "react";
import { toast } from "sonner";

import { EDGE_ENGINE, fetchVoicePreview, synthesizeWithEngine } from "@/api/domains/speech";
import { errorText } from "@/api/errorMessage";

/**
 * 选区工具条上的「朗读」:用**免费的 Edge 引擎**念,在本地播放,不建素材 —— 念完就没了;要留下来另点
 * 「存为音频素材」(那一步才走 /api/tts/synthesize 建任务、进素材库)。
 *
 * 走的是试听那条路(`POST /api/tts/preview`,同一个合成、记账照记),它一次只收 200 字以内,所以按句切成
 * 小段一段段念:念这一段时先去取下一段,段与段之间不留空当。不走对话音色(/api/agent/speech):那条要
 * 「让它出声」开着、用的是用户为智能体选的(可能收费的)嗓子,而这里说好了只用免费的那个。
 */

/** 一段最多多少字(试听接口的上限是 200,留点余量)。 */
export const READ_ALOUD_CHUNK = 180;
/** 存成素材时一次最多念多少字(/api/tts/synthesize 的上限)。 */
const SAVE_LIMIT = 2000;

/** 有中文用晓晓,否则用 Aria —— 都在 Edge 的内置音色表里(backend 的 EDGE_BUILTIN_VOICES)。 */
export function edgeVoiceFor(text: string): string {
  return /[\u3400-\u9fff]/.test(text) ? "zh-CN-XiaoxiaoNeural" : "en-US-AriaNeural";
}

/** 按句切成不超过 READ_ALOUD_CHUNK 字的小段;一句本身就超长的硬切。拼回去和原文一字不差。 */
export function splitForSpeech(text: string): string[] {
  if (!text.trim()) return [];
  const sentences = text.match(/[^。！？!?；;.\n]*[。！？!?；;.\n]+|[^。！？!?；;.\n]+$/g) ?? [text];
  const chunks: string[] = [];
  let current = "";
  for (const sentence of sentences) {
    for (let at = 0; at < sentence.length; at += READ_ALOUD_CHUNK) {
      const piece = sentence.slice(at, at + READ_ALOUD_CHUNK);
      if (current.length + piece.length > READ_ALOUD_CHUNK) {
        if (current) chunks.push(current);
        current = piece;
      } else current += piece;
    }
  }
  if (current) chunks.push(current);
  return chunks.filter((chunk) => chunk.trim());
}

export interface ReadAloud {
  reading: boolean;
  start: (text: string) => void;
  stop: () => void;
}

/**
 * 朗读的状态挂在编辑器上(不挂在工具条上):工具条跟着选区出现、消失,念到一半选区一变它就卸了 ——
 * 声音不该跟着断。
 */
export function useReadAloud(workspaceId: string, strings: { reading: string; stopReading: string; saveAudio: string; savingAudio: string }): ReadAloud {
  const [reading, setReading] = React.useState(false);
  const run = React.useRef(0);
  const audio = React.useRef<HTMLAudioElement | null>(null);
  const toastId = React.useRef<string | number | null>(null);
  const stop = React.useCallback(() => {
    run.current += 1;
    audio.current?.pause();
    audio.current = null;
    if (toastId.current != null) toast.dismiss(toastId.current);
    toastId.current = null;
    setReading(false);
  }, []);
  React.useEffect(() => stop, [stop]);
  const start = React.useCallback((text: string) => {
    stop();
    const chunks = splitForSpeech(text);
    if (!chunks.length) return;
    const voice = edgeVoiceFor(text);
    const mine = ++run.current;
    setReading(true);
    toastId.current = toast(strings.reading, {
      duration: Infinity,
      action: {
        label: strings.saveAudio,
        onClick: () => {
          void synthesizeWithEngine({ workspace_id: workspaceId, text: text.slice(0, SAVE_LIMIT), engine: EDGE_ENGINE, engine_voice: voice })
            .then(() => toast.success(strings.savingAudio))
            .catch((error) => toast.error(errorText(error)));
        },
      },
      cancel: { label: strings.stopReading, onClick: stop },
    });
    const fetchChunk = (chunk: string) => fetchVoicePreview({ workspace_id: workspaceId, engine: EDGE_ENGINE, voice, text: chunk });
    void (async () => {
      try {
        let next = fetchChunk(chunks[0]);
        for (let index = 0; index < chunks.length; index += 1) {
          const blob = await next;
          if (run.current !== mine) return;
          //: 念这一段的同时去取下一段,段与段之间不留空当。
          if (index + 1 < chunks.length) next = fetchChunk(chunks[index + 1]);
          await play(blob, audio);
          if (run.current !== mine) return;
        }
      } catch (error) {
        if (run.current === mine) toast.error(errorText(error));
      } finally {
        if (run.current === mine) stop();
      }
    })();
  }, [stop, strings, workspaceId]);
  return { reading, start, stop };
}

function play(blob: Blob, holder: React.MutableRefObject<HTMLAudioElement | null>): Promise<void> {
  const url = URL.createObjectURL(blob);
  const element = new Audio(url);
  holder.current = element;
  return new Promise<void>((resolve, reject) => {
    const done = () => { URL.revokeObjectURL(url); resolve(); };
    element.addEventListener("ended", done, { once: true });
    element.addEventListener("pause", done, { once: true });
    element.addEventListener("error", () => { URL.revokeObjectURL(url); reject(new Error("audio")); }, { once: true });
    element.play().catch((error: unknown) => { URL.revokeObjectURL(url); reject(error); });
  });
}
