import React from "react";
import { toast } from "sonner";

import {
  CLONE_ENGINE, EDGE_ENGINE, fetchVoicePreview, getAgentVoice, readWithAgentVoice, synthesizeVoice, synthesizeWithEngine,
  type AgentVoice,
} from "@/api/domains/speech";
import { errorText } from "@/api/errorMessage";

/**
 * 选区工具条上的「朗读」:在本地播放,不建素材 —— 念完就没了;要留下来另点「存为音频素材」(那一步才建任务、
 * 进素材库)。
 *
 * **用哪把嗓子**:他在设置「语音对话」里选好了的那一把(`POST /api/agent/speech/read`,只要求选好,不要求
 * 「让它出声」开着);没选过就用免费的 Edge(走试听那条路 `POST /api/tts/preview`),有中文用晓晓、否则 Aria。
 * 配音本身没有「默认音色」(引擎和音色每次成对点名,见 backend/domain/voices/speech),所以个人存着的音色只有
 * 这一份。选的是收费的引擎时照常按字符记账(和对话里念一句同一条路、同一道 ai 权限),提示条上写明用的是谁的声音。
 *
 * 按句切成小段一段段念:念这一段时先去取下一段,段与段之间不留空当;第一段出声也快。
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
export function useReadAloud(workspaceId: string, strings: { readingWithVoice: string; readingWithEdge: string; stopReading: string; saveAudio: string; savingAudio: string }): ReadAloud {
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
    const edgeVoice = edgeVoiceFor(text);
    const mine = ++run.current;
    setReading(true);
    void (async () => {
      try {
        //: 每次开念时现问一次:设置页刚改过音色,下一次朗读就该是新的那把。
        const pref = await getAgentVoice().catch(() => null);
        if (run.current !== mine) return;
        const chosen = pref?.engine && pref.engine_voice ? pref : null;
        toastId.current = toast(chosen ? strings.readingWithVoice : strings.readingWithEdge, {
          duration: Infinity,
          action: {
            label: strings.saveAudio,
            onClick: () => {
              void saveAsAudio(workspaceId, text.slice(0, SAVE_LIMIT), chosen, edgeVoice)
                .then(() => toast.success(strings.savingAudio))
                .catch((error) => toast.error(errorText(error)));
            },
          },
          cancel: { label: strings.stopReading, onClick: stop },
        });
        const fetchChunk = (chunk: string) => chosen
          ? readWithAgentVoice({ workspace_id: workspaceId, text: chunk })
          : fetchVoicePreview({ workspace_id: workspaceId, engine: EDGE_ENGINE, voice: edgeVoice, text: chunk });
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

/** 「存为音频素材」:用念的那把嗓子合成一份、进素材库(这一步建任务)。克隆音色走音色库那条路。 */
function saveAsAudio(workspaceId: string, text: string, chosen: AgentVoice | null, edgeVoice: string) {
  if (!chosen) return synthesizeWithEngine({ workspace_id: workspaceId, text, engine: EDGE_ENGINE, engine_voice: edgeVoice });
  if (chosen.engine === CLONE_ENGINE) return synthesizeVoice(chosen.voice_id || chosen.engine_voice, { text, speed: chosen.speed });
  return synthesizeWithEngine({
    workspace_id: workspaceId, text, engine: chosen.engine, engine_voice: chosen.engine_voice,
    engine_voice_resource: chosen.engine_voice_resource, speed: chosen.speed,
  });
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
