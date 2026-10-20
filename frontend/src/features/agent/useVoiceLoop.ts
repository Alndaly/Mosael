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

import { ApiError, dictate } from "@/api/client";
import {
  reportSpeechFailure,
  speechFailure as classifySpeechFailure,
  synthesizeSpeech,
  type SpeechFailure,
} from "@/features/agent/agentSpeech";
import { speakText } from "@/features/agent/speechPipeline";
import { loadSpeechMode, prefetchSpeechMode } from "@/features/agent/speechSettings";
import { useI18n } from "@/app/preferences";
import { playBlob, stopPlayback } from "@/lib/audioPlayback";
import { matchSpokenChoice } from "@/features/agent/spokenChoice";
import { UtteranceDetector } from "@/features/agent/utteranceDetector";

/** "transcribing" 是**录音已经停下、话还没换成文字**这一段。"thinking" 是话已经发出去、在等回复。
 *  分两种情况说,因为等待的长短和失败的原因都不一样 —— 识别首次还要载模型,那和模型跑得快不快无关;
 *  而用户在这两段里能做的事也不同(前者可以取消,后者不会)。
 *
 *  "synthesizing" 是**话已经有了、声音还没合成出来**这一段 —— 维护者报的正是它:「智能体助手在音频
 *  生成过程中没有 loading 以及对应 UI,生成语音时没有任何状态变化」。它此前和 "speaking" 共用一个
 *  状态,于是用户看到的是「它答完了」紧接「它已经在说」,而中间其实在等一次合成(远端引擎还要多一次
 *  往返)。"synthesisFailed" 是那一次合成没成:要说清原因、并且**点一下能重试** —— 语音模式下静默失败
 *  会被理解成「它没听见」,于是人再说一遍,然后再失败一次。 */
export type VoiceLoopState =
  | "off"
  | "listening"
  | "hearing"
  | "transcribing"
  | "thinking"
  | "synthesizing"
  | "synthesisFailed"
  | "speaking";

/** 每隔多久取一次音量。20 次/秒:够分辨句中停顿,又不至于让主线程忙起来。 */
const SAMPLE_MS = 50;

/** 消息发出去了、却迟迟没有任何信号(轮询没看到 `busy`,回复也没到)时,最多再把「在想」挂这么久。
 *  正常路径**不走它**:消息发出去时起表,轮询一旦看到这一轮在跑就作废,回复到了就直接切「生成语音中」。
 *  它只兜两种真会空下来的结局 —— 这一轮只调了工具、没有回复可念,以及轮询被某种原因错过。
 *  时长要明显大于会话轮询的 1.5 秒:否则每轮开头都会先闪一下「在听」,那正是这次要补的洞。 */
const TURN_WATCHDOG_MS = 4000;

export function useVoiceLoop({
  workspaceId,
  /** 把识别出来的一句话发出去。返回的 Promise 落定 = **这句话被收下了**,不是这一轮跑完了:
   *  回复还要等(可能是几十秒),那一段浮标说「在想」,由 `busy` / 回复自己收尾。 */
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
  const t = useI18n();
  const [state, setState] = React.useState<VoiceLoopState>("off");
  //: 当前音量,**以"开口阈值"为 1.0** 归一化。用 ref 不用 state:采样是 20 次/秒,
  //: 每次都 setState 会把整个浮标(以及它挂着的两个查询订阅)重渲染 20 次/秒,
  //: 而这个数只有一个消费者 —— 那几根条,它自己在 rAF 里读。
  const levelRef = React.useRef(0);
  //: 最近听清的一句。浮标把它显示出来 —— 语音里最让人不安的是"我说了,它有没有听见",
  //: 而把听到的原话摆出来一次性回答了这个问题(包括听错时,你当场就知道错在哪儿)。
  const [heard, setHeard] = React.useState("");
  //: 上一次开念失败的原因(和**能不能重试**)。浮标据此说清并给重试;清空的时机只有两个:
  //: 下一次真的开始合成、或者用户重新开口/关掉免提 —— 不能留一条永远挂在那儿的旧错。
  const [speechFailure, setSpeechFailure] = React.useState<SpeechFailure | null>(null);
  //: 最近一次交给合成的那段话。重试就是**再念一遍它** —— 失败之后用户不必再说一遍同样的话。
  const lastSpokenRef = React.useRef("");
  const stateRef = React.useRef<VoiceLoopState>("off");
  stateRef.current = state;
  //: 这一句已经发出去了、回复还没到。**发出之后不许把状态收回「在听」**:那一段是在等回复,
  //: 不是在等你说话。此前 `submit` 的 finally 正是这么做的 —— POST 一落定(只是消息被收下了)
  //: 就改回 listening,于是「转写成功」到「生成语音中」之间浮标什么都不说。
  const waitingRef = React.useRef(false);
  //: 看门狗的句柄。见 TURN_WATCHDOG_MS。
  const watchdogRef = React.useRef<number | null>(null);
  //: 外面那一轮此刻在不在跑 —— 给非渲染路径(submit 落定那一刻)读,免得看门狗盖住一轮真在跑的事。
  const busyRef = React.useRef(busy);
  busyRef.current = busy;
  //: 这一段等待的"代"。stop / 卸载把它加一 —— 迟到的识别结果据此知道自己已经过期:
  //: 不该再把"转写中"点亮,也不该替你把一句你其实已经取消的话发出去(取消就是取消)。
  const epochRef = React.useRef(0);
  //: 开念的"代"。打断、关掉免提、另一段声音接管都让它加一 —— 按句流水线据此把在途的合成作废,
  //: 也据此不再播下一句。**和识别的 epoch 分开**:说话打断的是声音,不是那句还没发出去的话。
  const speechRunRef = React.useRef(0);

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

  const disarmWatchdog = React.useCallback(() => {
    if (watchdogRef.current !== null) window.clearTimeout(watchdogRef.current);
    watchdogRef.current = null;
  }, []);

  /** **这一轮没有回复可念**时的出口:把「在想」收回「在听」,别留一个永远转的浮标。 */
  const settle = React.useCallback(() => {
    disarmWatchdog();
    if (!waitingRef.current) return;
    waitingRef.current = false;
    setState((current) => (current === "thinking" ? "listening" : current));
  }, [disarmWatchdog]);

  /** 起表。正常路径里它会被「看到这一轮在跑」或「回复到了」立刻作废,只有没有回复的那一轮会走到它。 */
  const armWatchdog = React.useCallback(() => {
    disarmWatchdog();
    watchdogRef.current = window.setTimeout(() => {
      watchdogRef.current = null;
      settle();
    }, TURN_WATCHDOG_MS);
  }, [disarmWatchdog, settle]);

  /**
   * 念一段话。**只有这一条路** —— 回复、确认卡、提问、失败,用户听到的都是同一个声音。
   *
   * 设置「念回复时先出声」(默认)时按句流水线:第一句合成完就播,后面的句子边播边取;
   * 选了「等整段」就一次取完。**设置只影响这条对话路**,文件类那几个入口不读它。
   */
  const say = React.useCallback(
    async (text: string) => {
      if (!text.trim()) return;
      const mine = (speechRunRef.current += 1);
      const cancelled = () => speechRunRef.current !== mine;
      //: **这一句开始处理了,等回复的那一段到此结束。** 看门狗也要收掉 —— 它会把正在生成的浮标
      //: 改回「在听」,而那已经不是真事了。
      waitingRef.current = false;
      disarmWatchdog();
      lastSpokenRef.current = text;
      setSpeechFailure(null);
      //: **合成不是"已经在说"。** 这一段此前和 speaking 共用状态,屏幕上看起来什么都没发生。
      //: 放在取设置之前:回复一到就该说"生成语音",别让一次设置往返又留下一段"在想"。
      setState((current) => (current === "off" ? current : "synthesizing"));
      const whole = (await loadSpeechMode()) === "whole";
      if (cancelled()) return;
      let failed = false;
      await speakText({
        text,
        synthesize: (one) => synthesizeSpeech(one, workspaceId),
        play: playBlob,
        whole,
        cancelled,
        //: 第一段音频真的要出声了,才切到"在说" —— 不是请求发出去的那一刻。
        onFirstAudio: () => {
          if (!cancelled()) setState((current) => (current === "off" ? current : "speaking"));
        },
        onFailure: (error) => {
          if (cancelled()) return;
          failed = true;
          setSpeechFailure(classifySpeechFailure(error, t("agentVoiceSpeakFailed")));
          setState((current) => (current === "off" ? current : "synthesisFailed"));
          //: toast 这一句照旧:人可能正看着别处,浮标也未必看得见。
          reportSpeechFailure(error, t("agentVoiceSpeakFailed"));
        },
      });
      if (cancelled() || failed) return;
      //: 念完(或被打断)都回到听 —— 语音模式下"没有下一步"等于死在那儿。
      setState((current) => (current === "speaking" || current === "synthesizing" ? "listening" : current));
    },
    [workspaceId, t, disarmWatchdog],
  );
  const sayRef = React.useRef(say);
  sayRef.current = say;

  const teardown = React.useCallback(() => {
    //: 先作废在途的识别:关掉免提、或者在"转写中"点那颗浮标,都不该在半分钟后冒出一条消息。
    epochRef.current += 1;
    //: 正在念的那一段也作废:在途的合成不该在关掉之后突然出声。
    speechRunRef.current += 1;
    //: 等回复的看门狗也停掉:关掉之后它不该再往一个已经关了的浮标上写状态。
    disarmWatchdog();
    waitingRef.current = false;
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
  }, [disarmWatchdog]);

  React.useEffect(() => teardown, [teardown]);
  //: 免提浮标一挂上就把「先出声 / 等整段」取回来,别让第一句等你一次往返。
  React.useEffect(() => {
    prefetchSpeechMode();
  }, []);

  /**
   * 外面那一轮在跑 → **浮标说"在想"**。这不是"在等你说话":模型在出字,工具在跑。
   *
   * 此前这里什么都没有,于是「在想」只出现在消息发出去到 POST 落定那几十毫秒里,后面整轮都
   * 被写成「在听」—— 维护者看到的空档就是它。
   *
   * 这一轮收尾了(`busy` 落回 false)则让看门狗起表:回复到了会立刻切「生成语音中」,没有回复
   * 可念的那一轮到点回「在听」。**不要在收尾时直接把状态改回"在听"** —— 回复那一行通常比
   * 状态轮询晚一点点到,先改"在听"就又闪出一个空档。
   */
  const on = state !== "off";
  React.useEffect(() => {
    if (!on) return;
    if (busy) {
      disarmWatchdog();
      setState((current) => (current === "listening" || current === "thinking" ? "thinking" : current));
      return;
    }
    if (waitingRef.current) armWatchdog();
  }, [busy, on, disarmWatchdog, armWatchdog]);

  /** 把这一段交上去识别,再发出去。`epoch` 是录音停下那一刻的代号:等待期间被取消/卸载就作废。 */
  const submit = React.useCallback(
    async (clip: Blob, epoch: number) => {
      if (epochRef.current !== epoch) return;
      //: **从录音停下到识别回来是一段没有声音的等待。** 用户看不见麦克风还在不在录,只看得见
      //: 浮标;不说"正在转写"的话,这段就是"它没听见"。首次识别还要载模型,这段可能有十几秒 ——
      //: 所以这里给的是"转写中",不是"在想"(那是话已经发出去、在等回复)。
      setState("transcribing");
      try {
        let text: string;
        try {
          text = ((await dictate(clip)).text ?? "").trim();
        } catch (error) {
          if (epochRef.current !== epoch) return;
          // **失败要出声(至少要看得见)。** 语音模式下用户多半没盯着屏幕,一次静默的失败
          // 会被理解成"它没听见",于是他再说一遍 —— 然后再失败一次。后端说了原因就照说。
          //: 失败发生在**识别**,不在发送:用说话输入既有那条 dictateFailed,
          //: "这句没能送出去"会把人指向错误的下一步。
          toast.error(error instanceof ApiError ? error.message : t("dictateFailed"));
          setState("listening");
          return;
        }
        if (epochRef.current !== epoch) return;
        setHeard(text);
        if (!text) {
          //: 和输入框那颗麦克风同一条:没听到内容要说出来 —— 否则这次等待结束得无声无息。
          toast.error(t("dictateHeardNothing"));
          setState("listening");
          return;
        }
        //: 话已经识别出来了,接下来才是"它在想"。**从这一刻起不许再收回"在听"** ——
        //: 那一段是在等回复,不是在等你说话。
        setState("thinking");
        waitingRef.current = true;
        // 有待答的选择题时,这一句是**答它**,不是一条新的指令 —— 否则模型会收到
        // 一句"告白场景",而它正等着你在卡片上点。
        const asked = questionRef.current;
        if (asked) {
          const match = matchSpokenChoice(text, asked.options);
          if (match.kind === "picked") {
            await onAnswerRef.current?.(match.index);
            //: 答完它通常接着跑一轮 —— 交给 busy / 下一次回复;没有下一轮就由看门狗收回"在听"。
            if (epochRef.current === epoch && !busyRef.current) armWatchdog();
            return;
          }
          // **拿不准就再问一次,不猜。** 猜错的代价是它顺着一条你没选的路做下去。
          await sayRef.current(
            match.kind === "ambiguous"
              ? t("agentVoiceChoiceAmbiguous").replace("{options}", match.indexes.map((one) => asked.options[one]).join(t("listSeparator")))
              : t("agentVoiceChoiceNone").replace("{options}", asked.options.join(t("listSeparator"))),
          );
          setState("listening");
          return;
        }
        try {
          await onUtteranceRef.current(text);
          //: **POST 落定 ≠ 这一轮跑完。** 它只说明消息被收下了;回复还在路上。这里必须留在
          //: 「在想」上,等 busy 接手(模型在出字)或者回复到了切「生成语音中」—— 此前这一句
          //: 之后的 finally 把它改回 "listening",那就是维护者截图里那段"什么都不显示"。
          if (epochRef.current === epoch && !busyRef.current) armWatchdog();
        } catch {
          if (epochRef.current !== epoch) return;
          waitingRef.current = false;
          disarmWatchdog();
          toast.error(t("agentVoiceSendFailed"));
          setState("listening");
        }
      } catch {
        //: 兜底:不能让一次意外把浮标钉在「转写中 / 在想」上 —— 那一代还在(没被取消/卸载)才收状态。
        if (epochRef.current === epoch) {
          waitingRef.current = false;
          disarmWatchdog();
          toast.error(t("agentVoiceSendFailed"));
          setState((current) => (current === "thinking" || current === "transcribing" ? "listening" : current));
        }
      }
    },
    [t, armWatchdog, disarmWatchdog],
  );

  const start = React.useCallback(async () => {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      toast.error(t("agentVoiceMicUnavailable"));
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
        //: 上一次合成的失败也到此为止:人已经在说下一句了,那条旧错不该还挂在浮标上。
        setSpeechFailure(null);
        //: 也要作废整条按句队列:只 stopPlayback 的话,播到一半的那句会结束、后面那句还会接着响。
        if (stateRef.current === "speaking") {
          speechRunRef.current += 1;
          stopPlayback();
        }
        setState("hearing");
        beginClip();
        return;
      }
      if ((event === "ended" || event === "discarded") && recorderRef.current) {
        const recorder = recorderRef.current;
        recorderRef.current = null;
        const keep = event === "ended";
        //: 这句话说完这一刻的代号。之后 stop / 卸载会让它过期 —— 那时这段录音不该再变成一句话。
        const epoch = epochRef.current;
        //: **停止录音这一秒就开始说"转写中"。** MediaRecorder 的 onstop 还要把最后一块数据
        //: 交上来,那之前界面不能还写着"听你说"(那是"你的话还在被录"的意思)。
        if (keep) setState("transcribing");
        recorder.onstop = () => {
          const clip = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
          chunksRef.current = [];
          // 咳嗽和键盘声录下来了,但不发 —— 发上去只会换回一句空识别。
          if (keep && clip.size > 0) void submit(clip, epoch);
          else setState("listening");
        };
        recorder.stop();
      }
    }, SAMPLE_MS);
  }, [submit, t]);

  const stop = React.useCallback(() => {
    teardown();
    stopPlayback();
    setSpeechFailure(null);
    setState("off");
  }, [teardown]);

  /** 再念一遍刚才没合成成功的那句话。**只重试合成,不让用户把话再说一遍** —— 他要的是听见它。 */
  const retrySpeech = React.useCallback(() => {
    const text = lastSpokenRef.current;
    if (!text) return;
    void sayRef.current(text);
  }, []);

  // 外面那一轮跑完、有话可念 —— 念出来。**状态由 say 自己走**(合成中 → 在说 → 回到听),
  // 这里只管"该念哪一句"。
  const spokenRef = React.useRef("");
  React.useEffect(() => {
    if (state === "off" || busy || !reply.trim() || reply === spokenRef.current) return;
    spokenRef.current = reply;
    void sayRef.current(reply);
  }, [busy, reply, state]);

  // 有待批准的变更 —— **只念,不接受语音批准**。
  //
  // 改工作流、建项目这类都要过确认卡,而确认卡的意义是"看得见的那道闸"。语音里说一声"好"
  // 就批准的话,识别错一个字的代价是它真的去改了你的东西 —— 而你多半没在看屏幕。所以这里
  // 只把"我要做什么"念出来,批准仍然要在屏幕上点。顺畅度让位给这一条。
  const announcedRef = React.useRef("");
  React.useEffect(() => {
    const pending = (pendingConfirmations ?? []).join(t("listSeparator"));
    if (state === "off" || !pending || pending === announcedRef.current) return;
    announcedRef.current = pending;
    void sayRef.current(t("agentVoiceConfirmPending").replace("{pending}", pending));
  }, [pendingConfirmations, state, t]);

  // 有待答的选择题 —— 念出来,然后等你说。
  const askedRef = React.useRef("");
  React.useEffect(() => {
    if (state === "off" || !question || question.question === askedRef.current) return;
    askedRef.current = question.question;
    void sayRef.current(
      t("agentVoiceQuestionOptions")
        .replace("{question}", question.question)
        .replace("{options}", question.options.join(t("listSeparator"))),
    );
  }, [question, state, t]);

  // 这一轮失败了 —— **必须出声**。语音模式下一次静默的失败会被理解成"它没听见",
  // 于是你再说一遍,然后再失败一次。
  const toldRef = React.useRef("");
  React.useEffect(() => {
    if (state === "off" || !failure || failure === toldRef.current) return;
    toldRef.current = failure;
    void sayRef.current(t("agentVoiceStepFailed").replace("{failure}", failure));
  }, [failure, state, t]);

  return { state, start, stop, on, levelRef, heard, speechFailure, retrySpeech };
}
