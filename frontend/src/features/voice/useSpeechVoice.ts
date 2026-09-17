import React from "react";
import { useQuery } from "@tanstack/react-query";

import { getTtsConfig, listTtsEngines, listTtsModels, listTtsVoices, listVoices } from "@/api/client";
import { pollWhileUnsettled } from "@/features/settings/pollWhileUnsettled";
import { speechEngineChoices } from "@/features/voice/speechEngines";

/** 合成请求里「谁来念」那几个字段。/voices/{id}/synthesize、/tts/synthesize、字幕配音收的都是它。 */
export type SpeechParams = {
  engine: string;
  voice_id?: string;
  clone_engine?: string;
  engine_voice?: string;
  engine_voice_resource?: string;
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
 * 界面在 SpeechVoiceFields,请求参数由 `params` 给出 —— 两条后端路由收的是同一组字段。
 */
export function useSpeechVoice(workspaceId: string) {
  // "clone" 是本地参考音克隆,要音色库里的一行;其余是远端引擎,自带发音人。
  const [engine, setEngineState] = React.useState("clone");
  const [voiceChoice, setVoiceChoice] = React.useState<string | null>(null);
  const [engineVoiceChoice, setEngineVoiceChoice] = React.useState("");
  const [cloneEngineChoice, setCloneEngineChoice] = React.useState("");
  const [speed, setSpeed] = React.useState(1);

  // staleTime 不能是 Infinity:这里带着"本地引擎装了没有",而用户就是会在设置页装完再回来。
  const engines = useQuery({ queryKey: ["tts-engines"], queryFn: listTtsEngines, staleTime: 30_000 });
  const voices = useQuery({ queryKey: ["voices", workspaceId], queryFn: () => listVoices(workspaceId) });
  // 本地引擎的就绪情况是后台探出来的,第一次拿到的必然是「还没测过」—— 没测完就接着问,
  // 判据与设置页共用 pollWhileUnsettled。
  const runtimes = useQuery({
    queryKey: ["tts-models"],
    queryFn: listTtsModels,
    staleTime: 30_000,
    refetchInterval: (query) => pollWhileUnsettled(query.state.data),
  });
  const ttsConfig = useQuery({ queryKey: ["tts-config"], queryFn: getTtsConfig, staleTime: 30_000 });
  // 发音人按引擎现拉:火山的目录跟着账号走,不是引擎列表的一部分。
  const engineVoices = useQuery({
    queryKey: ["tts-voices", engine],
    queryFn: () => listTtsVoices(engine),
    enabled: engine !== "clone",
  });

  const setEngine = (next: string) => {
    setEngineState(next);
    // 发音人 id 不跨引擎("alloy" 对火山毫无意义),新引擎的目录又是异步到的 —— 清掉,不猜。
    setEngineVoiceChoice("");
  };

  const library = voices.data ?? [];
  const voiceId = voiceChoice ?? library[0]?.id ?? "";
  // 设置页那个是默认,这一次用哪个由这一次说了算。
  const cloneEngine = cloneEngineChoice || ttsConfig.data?.engine || "f5-tts";
  const cloneRuntime = (runtimes.data ?? []).find((item) => item.id === cloneEngine);
  // 能出声要两件事都成立:有解释器能 import 它,权重在盘上。还在探测时也不给点 —— 那一刻
  // 确实不知道跑不跑得起来,而按下去的代价是一次必然失败的合成(下拉里同时写着「检测中」)。
  const cloneUsable = runtimeState(cloneRuntime) === "ready";

  const activeEngine = engines.data?.find((item) => item.id === engine);
  const voiceChoices = engineVoices.data ?? [];
  // 下拉在没选时**显示**第一个,那就提交同一个 —— 否则引擎会安静地用它自己的默认音。
  const engineVoice = engineVoiceChoice || voiceChoices[0]?.value || "";
  const chosenVoice = voiceChoices.find((item) => item.value === engineVoice);

  // 语速跟着**引擎能力**走:F5 吃 speed,fish 的请求里根本没有这一项;百炼的 qwen-tts 也没有。
  // 远端引擎缺这个字段时按支持处理(老引擎行为不变)。
  const speedSupported =
    engine === "clone" ? Boolean(cloneRuntime?.supports_speed) : activeEngine?.supports_speed !== false;

  // 克隆要有音色且引擎装好;远端引擎要么有目录,要么它自己说需要手填 id 而用户填了。
  const ready =
    engine === "clone"
      ? Boolean(voiceId) && cloneUsable
      : voiceChoices.length > 0 || !activeEngine?.needs_voice_id || Boolean(engineVoiceChoice.trim());

  // 不支持语速时**不发** —— 发了也只会被忽略,而"传了却没用"正是那种谎。
  const params: SpeechParams =
    engine === "clone"
      ? { engine, voice_id: voiceId, clone_engine: cloneEngine, ...(speedSupported ? { speed } : {}) }
      : {
          engine,
          engine_voice: engineVoice,
          // 只有目录知道的资源族;不带的话火山回一个 55000000。
          engine_voice_resource: chosenVoice?.resource_id ?? "",
          ...(speedSupported ? { speed } : {}),
        };

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
    runtimes: runtimes.data ?? [],
    cloneEngine,
    setCloneEngine: setCloneEngineChoice,
    cloneRuntime,
    voiceChoices,
    engineVoice,
    /** 用户亲手选过/填过的那个;空 = 还没动过(可以替他挑一个合适的)。 */
    engineVoiceChoice,
    setEngineVoice: setEngineVoiceChoice,
    speed,
    setSpeed,
    speedSupported,
    ready,
    params,
  };
}

export type SpeechVoice = ReturnType<typeof useSpeechVoice>;
