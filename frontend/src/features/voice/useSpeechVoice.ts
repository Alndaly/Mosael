import React from "react";
import { useQuery } from "@tanstack/react-query";

import { getTtsConfig, listTtsEngines, listTtsModels, listTtsVoices } from "@/api/client";
import { voiceKeys } from "@/api/queryKeys";
import { pollWhileUnsettled } from "@/lib/pollWhileUnsettled";
import { speechEngineChoices } from "@/features/voice/speechEngines";
import { useVoiceLibrary } from "@/features/voice/useVoiceLibrary";
import { CLONE_ENGINE, clonedVoiceRef, isClonedVoice, voiceRefOf, type VoiceRef } from "@/api/domains/speech";
import type { MessageKey } from "@/app/messages";

/** 合成请求里「谁来念、念多快」那两格。/tts/synthesize、字幕配音、创作页的语音收的都是它。
 *  `voice` 是一把嗓子(ADR 0087 的 `VoiceRef`);还没选好时是 `null`。 */
export type SpeechChoice = {
  voice: VoiceRef | null;
  speed?: number;
};

type LocalRuntime = { status: string; runtime_ready: boolean; runtime_checked: boolean };

/**
 * 本地引擎现在的状态,三态。**「还没测过」不是「跑不起来」**:探测要起子进程去 import,
 * 第一次拿到的必然是还没测过,那时 runtime_ready 是 false,含义却是"未知"。
 */
export function runtimeState(runtime: LocalRuntime | undefined): "checking" | "ready" | "unready" {
  if (!runtime || !runtime.runtime_checked) return "checking";
  return runtime.status === "installed" && runtime.runtime_ready ? "ready" : "unready";
}

/**
 * 「用哪个引擎、哪个声音来念」—— 念一段文字、给字幕配音问的都是这一件事。
 *
 * 此前配音面板和字幕配音弹层各有一份:一份能换克隆引擎、能调语速,另一份不能;一份判断了
 * 「本地引擎装没装好」,另一份没判,于是同一个选择在两处得到两种结果。现在状态和判据在这里,
 * 界面在 SpeechVoiceFields,请求里那两格由 `choice` 给出 —— 后端每一条念字的路由收的都是它。
 */
export function useSpeechVoice(workspaceId: string) {
  // "clone" 是本地参考音克隆,要音色库里的一行;其余是远端引擎,自带发音人。
  const [engine, setEngineState] = React.useState(CLONE_ENGINE);
  const [voiceChoice, setVoiceChoice] = React.useState<string | null>(null);
  const [engineVoiceChoice, setEngineVoiceChoice] = React.useState("");
  const [cloneEngineChoice, setCloneEngineChoice] = React.useState("");
  //: 本机克隆明说用哪一份权重(F5 按语言分的那几份);空 = 按文字自动挑。法语、德语都写拉丁字母,自动挑永远挑不中。
  const [cloneWeights, setCloneWeights] = React.useState("");
  const [speed, setSpeed] = React.useState(1);

  // staleTime 不能是 Infinity:这里带着"本地引擎装了没有",而用户就是会在设置页装完再回来。
  const engines = useQuery({ queryKey: ["tts-engines"], queryFn: listTtsEngines, staleTime: 30_000 });
  const voices = useVoiceLibrary(workspaceId);
  // 本地引擎的就绪情况是后台探出来的,第一次拿到的必然是「还没测过」—— 没测完就接着问,
  // 判据与设置页共用 pollWhileUnsettled。
  const runtimes = useQuery({
    queryKey: ["tts-models"],
    queryFn: listTtsModels,
    staleTime: 30_000,
    refetchInterval: (query) => pollWhileUnsettled(query.state.data),
  });
  const ttsConfig = useQuery({ queryKey: ["tts-config"], queryFn: getTtsConfig, staleTime: 30_000 });
  // 发音人按引擎现拉:火山的目录跟着账号走,不是引擎列表的一部分。带上工作区:能复刻的引擎(CosyVoice)
  // 还列这个工作区配音库里的嗓子(`cloned`)。
  const engineVoices = useQuery({
    queryKey: voiceKeys.engineVoices(engine, workspaceId),
    queryFn: () => listTtsVoices(engine, workspaceId),
    enabled: engine !== CLONE_ENGINE,
  });

  const setEngine = (next: string) => {
    setEngineState(next);
    // 发音人 id 不跨引擎("alloy" 对火山毫无意义),新引擎的目录又是异步到的 —— 清掉,不猜。
    setEngineVoiceChoice("");
  };

  const library = voices.data ?? [];
  const voiceId = voiceChoice ?? library[0]?.id ?? "";
  // 设置页那个是默认,这一次用哪个由这一次说了算。
  //: 「克隆引擎」只列能克隆的那几个:Qwen3-TTS 也在本机引擎清单里,但它只念预置音色,是另一个念字引擎。
  const cloneRuntimes = (runtimes.data ?? []).filter((item) => item.clones_voices);
  const cloneEngine = cloneEngineChoice || ttsConfig.data?.engine || "f5-tts";
  const cloneRuntime = cloneRuntimes.find((item) => item.id === cloneEngine);
  // 能出声要两件事都成立:有解释器能 import 它,权重在盘上。还在探测时也不给点 —— 那一刻
  // 确实不知道跑不跑得起来,而按下去的代价是一次必然失败的合成(下拉里同时写着「检测中」)。
  const cloneState = runtimeState(cloneRuntime);

  const activeEngine = engines.data?.find((item) => item.id === engine);
  const voiceChoices = engineVoices.data ?? [];
  //: 引擎自己的音色(系统音色)和配音库里的嗓子(克隆音色,只有能复刻的引擎才有)。
  const stockVoices = voiceChoices.filter((item) => !isClonedVoice(item));
  const clonedVoices = voiceChoices.filter(isClonedVoice);
  // 下拉在没选时**显示**第一个,那就提交同一个 —— 否则引擎会安静地用它自己的默认音。
  // 默认落在系统音色上,**不落在克隆音色上**:那一下要把参考音频传到第三方,得是人亲手点的。
  const engineVoice = engineVoiceChoice || stockVoices[0]?.id || "";
  const chosenVoice = voiceChoices.find((item) => item.id === engineVoice);
  const speaksClonedVoice = isClonedVoice(chosenVoice);

  // 语速跟着**引擎能力**走:F5 吃 speed,fish 的请求里根本没有这一项;百炼的 qwen-tts 也没有。
  // 远端引擎缺这个字段时按支持处理(老引擎行为不变)。
  const speedSupported =
    engine === CLONE_ENGINE ? Boolean(cloneRuntime?.supports_speed) : activeEngine?.supports_speed !== false;

  // 还念不了的原因(文案 key);null = 谁来念已经定好。按钮「点不点得了」和悬停时「为什么」都用它,不各判一套。
  // 克隆要有音色且引擎装好;远端引擎要能用,并且要么有目录,要么它自己说需要手填 id 而用户填了(或点了一把克隆音色)。
  const voiceBlocker: MessageKey | null =
    engine === CLONE_ENGINE
      ? !voiceId
        ? "speechBlockedPickVoice"
        : cloneState === "checking"
          ? "speechBlockedCheckingClone"
          : cloneState === "unready"
            ? "createCloneNotInstalled"
            : null
      : activeEngine?.ready === false
        ? "createEngineNotReady"
        : stockVoices.length > 0 || !activeEngine?.needs_voice_id || engineVoiceChoice.trim()
          ? null
          : "speechBlockedNeedsVoiceId";

  // 本机克隆的引擎 / 权重写在嗓子的 `model` 里(`f5-tts/fr`);权重只有 F5 才分。
  const cloneModel = [cloneEngine, cloneEngine === "f5-tts" ? cloneWeights : ""].filter(Boolean).join("/");
  const voiceRef: VoiceRef | null =
    engine === CLONE_ENGINE
      ? voiceId
        ? clonedVoiceRef(voiceId, cloneModel)
        : null
      : engineVoice
        ? // 目录里那一项(带着只有目录知道的 extra,火山的资源族);手填的 id 没有目录行,就是一个裸的引擎音色。
          voiceRefOf(engine, chosenVoice ?? { id: engineVoice, source: "builtin", extra: {} })
        : null;
  // 不支持语速时**不发** —— 发了也只会被忽略,而"传了却没用"正是那种谎。
  const choice: SpeechChoice = { voice: voiceRef, ...(speedSupported ? { speed } : {}) };

  return {
    engine,
    setEngine,
    engines: speechEngineChoices(engines.data),
    activeEngine,
    library,
    libraryLoaded: voices.isSuccess,
    libraryLoading: voices.isLoading,
    voiceId,
    setVoiceId: setVoiceChoice,
    /** 能克隆的本机引擎(克隆引擎下拉的选项)。 */
    cloneRuntimes,
    cloneEngine,
    setCloneEngine: setCloneEngineChoice,
    cloneWeights,
    setCloneWeights,
    cloneRuntime,
    voiceChoices,
    /** 引擎自己的音色(不含配音库里的嗓子)。按文字替人挑发音人时只在这里挑。 */
    stockVoices,
    /** 这个引擎念得了的配音库嗓子(只有能复刻的引擎才有)。 */
    clonedVoices,
    engineVoice,
    /** 选中的那一项音色(目录里的那一行);手填 id、还没拉到目录时没有。 */
    chosenVoice,
    /** 选中的是配音库里的一把嗓子(由远端引擎念它的副本)。 */
    speaksClonedVoice,
    /** 用户亲手选过/填过的那个;空 = 还没动过(可以替他挑一个合适的)。 */
    engineVoiceChoice,
    setEngineVoice: setEngineVoiceChoice,
    speed,
    setSpeed,
    speedSupported,
    voiceBlocker,
    choice,
  };
}

export type SpeechVoice = ReturnType<typeof useSpeechVoice>;
