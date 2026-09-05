/**
 * 免提对话:麦克风一直开着,说完一句就发出去,它答完再念给你听。
 *
 * 这是把已有的几块接成一个环,而不是另起一套:
 *
 *     麦克风 → UtteranceDetector 分句 → /api/asr/dictate 识别 → 发消息 → 回合
 *            → SpeakButton 那条临时合成的路念出来 → 回到听
 *
 * **打断(barge-in)是同一个 VAD 的副产品。** 它在念的时候你开口了 —— 检测器照样在跑,
 * 一见 "speaking" 就把播放掐掉、开始录你这一句。不这样的话,你得等它念完才能纠正它,
 * 而"念错了还要听完"正是语音助手最让人恼火的地方。
 *
 * 录音是**分段的**:每句话一个 MediaRecorder。用一个长录音再按时间戳切的话,切点要在
 * 容器格式里找关键帧,而 webm/opus 不保证在任意时刻可切 —— 一段一个录音器省掉整个问题。
 */

import React from "react";
import { toast } from "sonner";

import { API_BASE, getAuthToken } from "@/api/client";
import { playSpeech, stopSpeaking } from "@/components/agent/speechPlayback";
import { matchSpokenChoice } from "@/components/agent/spokenChoice";
import { UtteranceDetector } from "@/components/agent/utteranceDetector";

export type VoiceLoopState = "off" | "listening" | "hearing" | "thinking" | "speaking";

/** 每隔多久取一次音量。20 次/秒:够分辨句中停顿,又不至于让主线程忙起来。 */
const SAMPLE_MS = 50;

export function useVoiceLoop({
  workspaceId,
  /** 把识别出来的一句话发出去。返回的 Promise 落定 = 这一轮跑完了。 */
  onUtterance,
  /** 这一轮的回复,用来念。空串 = 没什么可念的(比如只调了工具)。 */
  reply,
  /** 外面那一轮还在跑吗 —— 语音模式下"在想"就是它。 */
  busy,
  /** 待答的选择题。有它的时候,下一句话是**答它**,不是发给模型。 */
  question,
  /** 用语音答了。 */
  onAnswer,
  /** 待批准的变更卡。**只念,不接受语音批准** —— 见下面那段说明。 */
  pendingConfirmations,
  /** 这一轮失败了,失败原因。语音模式下静默失败会被理解成"它没听见"。 */
  failure,
}: {
  workspaceId: string;
  onUtterance: (text: string) => Promise<void> | void;
  reply: string;
  busy: boolean;
  question?: { question: string; options: string[] } | null;
  onAnswer?: (index: number) => Promise<void> | void;
  pendingConfirmations?: string[];
  failure?: string;
}) {
  const [state, setState] = React.useState<VoiceLoopState>("off");
  //: 当前音量,**以"开口阈值"为 1.0** 归一化。用 ref 不用 state:采样是 20 次/秒,
  //: 每次都 setState 会把整个浮标(以及它挂着的两个查询订阅)重渲染 20 次/秒,
  //: 而这个数只有一个消费者 —— 那几根条,它自己在 rAF 里读。
  const levelRef = React.useRef(0);
  //: 最近听清的一句。浮标把它显示出来 —— 语音里最让人不安的是"我说了,它有没有听见",
  //: 而把听到的原话摆出来一次性回答了这个问题(包括听错时,你当场就知道错在哪儿)。
  const [heard, setHeard] = React.useState("");
  const stateRef = React.useRef<VoiceLoopState>("off");
  stateRef.current = state;

  const streamRef = React.useRef<MediaStream | null>(null);
  const contextRef = React.useRef<AudioContext | null>(null);
  const timerRef = React.useRef<number | null>(null);
  const recorderRef = React.useRef<MediaRecorder | null>(null);
  const chunksRef = React.useRef<BlobPart[]>([]);
  const detectorRef = React.useRef(new UtteranceDetector());
  const onUtteranceRef = React.useRef(onUtterance);
  onUtteranceRef.current = onUtterance;
  const questionRef = React.useRef(question);
  questionRef.current = question;
  const onAnswerRef = React.useRef(onAnswer);
  onAnswerRef.current = onAnswer;

  /** 念一句话。**只有这一条路** —— 回复、确认卡、提问、失败,用户听到的都是同一个声音。 */
  const say = React.useCallback(
    async (text: string) => {
      if (!text.trim()) return;
      try {
        const token = getAuthToken();
        const response = await fetch(`${API_BASE}/api/agent/speech`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({ text: text.slice(0, 4000), workspace_id: workspaceId }),
        });
        if (!response.ok) {
          const detail = (await response.json().catch(() => null))?.detail;
          toast[response.status === 409 ? "message" : "error"](detail || "这段没能念出来");
          return;
        }
        await playSpeech(await response.blob());
      } catch {
        toast.error("这段没能念出来");
      }
    },
    [workspaceId],
  );
  const sayRef = React.useRef(say);
  sayRef.current = say;

  const teardown = React.useCallback(() => {
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
    timerRef.current = null;
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    recorderRef.current = null;
    void contextRef.current?.close().catch(() => undefined);
    contextRef.current = null;
    // 轨道要关 —— 否则系统的录音指示灯一直亮着,而用户以为已经关掉了。
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    detectorRef.current.reset();
    levelRef.current = 0;
  }, []);

  React.useEffect(() => teardown, [teardown]);

  /** 把这一段交上去识别,再发出去。 */
  const submit = React.useCallback(
    async (clip: Blob) => {
      setState("thinking");
      try {
        const body = new FormData();
        body.append("clip", clip, "clip.webm");
        const token = getAuthToken();
        const response = await fetch(`${API_BASE}/api/asr/dictate`, {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          body,
        });
        const payload = (await response.json().catch(() => null)) as { text?: string; detail?: string } | null;
        if (!response.ok) {
          // **失败要出声(至少要看得见)。** 语音模式下用户多半没盯着屏幕,一次静默的失败
          // 会被理解成"它没听见",于是他再说一遍 —— 然后再失败一次。
          toast.error(payload?.detail || "这句没听清");
          setState("listening");
          return;
        }
        const text = (payload?.text ?? "").trim();
        setHeard(text);
        if (!text) {
          setState("listening");
          return;
        }
        // 有待答的选择题时,这一句是**答它**,不是一条新的指令 —— 否则模型会收到
        // 一句"告白场景",而它正等着你在卡片上点。
        const asked = questionRef.current;
        if (asked) {
          const match = matchSpokenChoice(text, asked.options);
          if (match.kind === "picked") {
            await onAnswerRef.current?.(match.index);
            return;
          }
          // **拿不准就再问一次,不猜。** 猜错的代价是它顺着一条你没选的路做下去。
          await sayRef.current(
            match.kind === "ambiguous"
              ? `这几个都像:${match.indexes.map((one) => asked.options[one]).join("、")}。说得再具体一点?`
              : `没对上任何一个。可以说第几个,或者念出选项:${asked.options.join("、")}`,
          );
          setState("listening");
          return;
        }
        await onUtteranceRef.current(text);
      } catch {
        toast.error("这句没能送出去");
      } finally {
        setState((current) => (current === "thinking" ? "listening" : current));
      }
    },
    [],
  );

  const start = React.useCallback(async () => {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      toast.error("用不了麦克风");
      return;
    }
    streamRef.current = stream;
    const context = new AudioContext();
    contextRef.current = context;
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    context.createMediaStreamSource(stream).connect(analyser);
    const buffer = new Float32Array(analyser.fftSize);
    setState("listening");

    const beginClip = () => {
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => event.data.size > 0 && chunksRef.current.push(event.data);
      recorder.start();
      recorderRef.current = recorder;
    };

    timerRef.current = window.setInterval(() => {
      analyser.getFloatTimeDomainData(buffer);
      let sum = 0;
      for (const sample of buffer) sum += sample * sample;
      const rms = Math.sqrt(sum / buffer.length);
      const event = detectorRef.current.push(rms, performance.now());
      // 阈值 = 1.0。上限放到 2.5 而不是 1:顶格之后再大声也没有反馈,人会以为它卡住了。
      levelRef.current = Math.min(rms / Math.max(detectorRef.current.triggerLevel, 1e-6), 2.5);

      if (event === "speaking" && !recorderRef.current) {
        // **打断在这里发生。** 它正在念,而你开口了 —— 掐掉播放,开始录。
        if (stateRef.current === "speaking") stopSpeaking();
        setState("hearing");
        beginClip();
        return;
      }
      if ((event === "ended" || event === "discarded") && recorderRef.current) {
        const recorder = recorderRef.current;
        recorderRef.current = null;
        const keep = event === "ended";
        recorder.onstop = () => {
          const clip = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
          chunksRef.current = [];
          // 咳嗽和键盘声录下来了,但不发 —— 发上去只会换回一句空识别。
          if (keep && clip.size > 0) void submit(clip);
          else setState("listening");
        };
        recorder.stop();
      }
    }, SAMPLE_MS);
  }, [submit]);

  const stop = React.useCallback(() => {
    teardown();
    stopSpeaking();
    setState("off");
  }, [teardown]);

  // 外面那一轮跑完、有话可念 —— 念出来,念完回到听。
  const spokenRef = React.useRef("");
  React.useEffect(() => {
    if (state === "off" || busy || !reply.trim() || reply === spokenRef.current) return;
    spokenRef.current = reply;
    setState("speaking");
    void (async () => {
      await sayRef.current(reply);
      // 念完(或被打断)都回到听 —— 语音模式下"没有下一步"等于死在那儿。
      setState((current) => (current === "speaking" ? "listening" : current));
    })();
  }, [busy, reply, state]);

  // 有待批准的变更 —— **只念,不接受语音批准**。
  //
  // 改工作流、建项目这类都要过确认卡,而确认卡的意义是"看得见的那道闸"。语音里说一声"好"
  // 就批准的话,识别错一个字的代价是它真的去改了你的东西 —— 而你多半没在看屏幕。所以这里
  // 只把"我要做什么"念出来,批准仍然要在屏幕上点。顺畅度让位给这一条。
  const announcedRef = React.useRef("");
  React.useEffect(() => {
    const pending = (pendingConfirmations ?? []).join("、");
    if (state === "off" || !pending || pending === announcedRef.current) return;
    announcedRef.current = pending;
    void sayRef.current(`我要${pending}。这一步会改东西,去屏幕上确认一下。`);
  }, [pendingConfirmations, state]);

  // 有待答的选择题 —— 念出来,然后等你说。
  const askedRef = React.useRef("");
  React.useEffect(() => {
    if (state === "off" || !question || question.question === askedRef.current) return;
    askedRef.current = question.question;
    void sayRef.current(`${question.question} 可选:${question.options.join("、")}。`);
  }, [question, state]);

  // 这一轮失败了 —— **必须出声**。语音模式下一次静默的失败会被理解成"它没听见",
  // 于是你再说一遍,然后再失败一次。
  const toldRef = React.useRef("");
  React.useEffect(() => {
    if (state === "off" || !failure || failure === toldRef.current) return;
    toldRef.current = failure;
    void sayRef.current(`刚才那一步没成:${failure}`);
  }, [failure, state]);

  return { state, start, stop, on: state !== "off", levelRef, heard };
}
