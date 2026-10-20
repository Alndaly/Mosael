/**
 * 语音对话用哪个音色,以及说话输入(ASR)用哪一家。
 *
 * **和配音的默认音色是两份配置,而这一节存在的理由就是那句话。** 配音要质量:本地零样本
 * 引擎、克隆出来的音色,首次加载十几分钟也认,因为那段音频要进成片。对话要延迟:说完一句
 * 等一分钟就不叫对话了。同一个默认同时服务这两件事,必然在某一边是错的。
 *
 * 引擎与音色的清单**问的是同一组接口**(listTtsEngines / listTtsVoices),和配音面板同源 ——
 * 这里只是另一处选择,不是另一份目录。说话输入底下没有自己的目录:候选就是「转写」那项能力的
 * 候选(能力表),只列已经就绪的;空着 = 跟随转写默认,和这一格出现之前的行为完全一致。
 *
 * 「念回复时先出声」也在这里:先出声 = 第一句合成完就播、后面的边播边取;等整段 = 整段合成完再播。
 * **它是对话类的开关** —— 工作流「语音合成」节点、画板音配音、笔记「存成素材」都不读它。
 */

import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  fetchAgentVoicePreview,
  getAgentVoice,
  listAsrModels,
  listCapabilityChoices,
  listTtsEngines,
  listTtsVoices,
  setAgentVoice,
} from "@/api/client";
import { capabilityKeys, voiceKeys } from "@/api/queryKeys";
import { useI18n, usePreferences } from "@/app/preferences";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { OptionPicker } from "@/components/ui/option-picker";
import { Segmented } from "@/components/ui/segmented";
import { Switch } from "@/components/ui/switch";
import { SETTINGS_FIELD_WIDTH, SettingsGroup, SettingsRow } from "@/components/settings/settings-layout";
import { VoicePreviewButton } from "@/components/app/VoicePreviewButton";
import { isConsentDeclined, withRemoteVoiceConsent } from "@/features/voice/remoteVoiceConsent";
import { rememberSpeechMode, speechModeOf, type SpeechMode } from "@/features/agent/speechSettings";

const SPEEDS = [0.75, 1, 1.25, 1.5, 2];
/** Radix 的下拉项不许用空串当 value;空串在库里表示「跟随转写」,这里换一个哨兵。 */
const FOLLOW_TRANSCRIPTION = "__follow_transcription__";

export function AgentVoiceSection({ workspaceId }: { workspaceId: string }) {
  const t = useI18n();
  const { voiceDock, setVoiceDock } = usePreferences();
  const qc = useQueryClient();
  const pref = useQuery({ queryKey: ["agent-voice"], queryFn: getAgentVoice });
  const engines = useQuery({ queryKey: ["tts-engines"], queryFn: listTtsEngines, staleTime: 30_000 });
  //: 说话输入的候选就是「转写」那项能力的候选 —— 和「设置 → 能力提供方」同源,不是另一份目录。
  const capabilities = useQuery({ queryKey: capabilityKeys.choices(), queryFn: listCapabilityChoices, staleTime: 30_000 });
  //: 「留空 = 跟随转写默认」到底是谁:管理里设的那一份(只读,拿来把这一格说清楚)。
  //: 这个人自己又在「能力提供方 → 转写」定过的话,那比部署默认更具体 —— 显示那个。
  const asrModels = useQuery({ queryKey: ["asr-models"], queryFn: listAsrModels, staleTime: 60_000 });

  const [engine, setEngine] = React.useState("");
  const [voice, setVoice] = React.useState("");
  const [speed, setSpeed] = React.useState(1);
  const [asrEngine, setAsrEngine] = React.useState("");
  const [speakEarly, setSpeakEarly] = React.useState(true);
  // 服务端那份到了之后水合一次。**之后不再回灌** —— 否则用户改了一半会被一次后台刷新盖掉。
  const hydrated = React.useRef(false);
  const savedAsrRef = React.useRef("");
  const savedSpeakEarlyRef = React.useRef(true);
  React.useEffect(() => {
    if (hydrated.current || !pref.data) return;
    hydrated.current = true;
    setEngine(pref.data.engine);
    //: 音色那一格:引擎自己的,或者(CosyVoice)配音库里的一把嗓子 —— 存在 voice_id 上(ADR 0037)。
    setVoice(pref.data.engine_voice || pref.data.voice_id || "");
    setSpeed(pref.data.speed || 1);
    setAsrEngine(pref.data.asr_engine ?? "");
    savedAsrRef.current = pref.data.asr_engine ?? "";
    setSpeakEarly(pref.data.speak_early !== false);
    savedSpeakEarlyRef.current = pref.data.speak_early !== false;
    //: 设置页拿到的就是对话类要用的那份;写进缓存,别让下一次开口再等一次往返。
    rememberSpeechMode(speechModeOf(pref.data));
  }, [pref.data]);

  //: 带上工作区:CosyVoice 还列这个工作区配音库里的嗓子(`cloned`)。
  const voices = useQuery({
    queryKey: voiceKeys.engineVoices(engine, workspaceId),
    queryFn: () => listTtsVoices(engine, workspaceId),
    enabled: Boolean(engine),
  });
  const voiceChoices = voices.data ?? [];
  const chosen = voiceChoices.find((one) => one.value === voice);
  const cloned = Boolean(chosen?.cloned);
  const hasCloned = voiceChoices.some((one) => one.cloned);
  //: 只有就绪的转写候选能选:缺密钥 / 没装运行环境的,列出来只会让人选中之后才失败
  //: (和上面 TTS 引擎那一格同一条规矩)。
  const dictationChoices = ((capabilities.data ?? [])
    .find((one) => one.capability === "transcription")?.options ?? [])
    .filter((one) => (one.missing ?? []).length === 0);
  //: 「跟随默认」不是一张空白卡片:把此刻它实际会用的那一份写出来。
  //: 这个人在「能力提供方 → 转写」定过的话用那个(那是一次更具体的选择);否则就是管理里设的默认模型。
  const transcriptionChoice = capabilities.data?.find((one) => one.capability === "transcription");
  const personalTranscription = transcriptionChoice?.current
    ? (transcriptionChoice.options ?? []).find((one) => one.id === transcriptionChoice.current)?.name ?? ""
    : "";
  const defaultTranscriptionModel = (asrModels.data ?? []).find((one) => one.is_default);
  const followTranscription = personalTranscription || defaultTranscriptionModel?.label || "";

  const save = useMutation({
    //: 点了配音库里的嗓子:这个账号第一次用它,先问一次要不要传上去(ADR 0037),同意了再存。
    mutationFn: (enabled: boolean) =>
      withRemoteVoiceConsent(() =>
        setAgentVoice({
          engine,
          engine_voice: cloned ? "" : voice,
          engine_voice_resource: cloned ? "" : (chosen?.resource_id ?? ""),
          engine_model: "",
          provider_profile_id: null,
          voice_id: cloned ? voice : null,
          speed,
          enabled,
          asr_engine: asrEngine,
          speak_early: speakEarly,
        }),
      ),
    // 回包就是存下的那份:直接放进缓存,试听键不必等一次重新拉取才知道「屏幕上的已经存好了」。
    onSuccess: (saved) => {
      qc.setQueryData(["agent-voice"], saved);
      rememberSpeechMode(speechModeOf(saved));
    },
    onError: (error: Error) => {
      //: 不同意上传:这把嗓子没存上,屏幕上也别留着它(像是选好了),清掉让人重挑。
      if (isConsentDeclined(error)) setVoice("");
      else toast.error(error.message);
    },
  });

  //: 说话输入那一格**不跟着音色走**:只改它的时候不该顺手把还没选全的 TTS 组合(新引擎 + 空音色)
  //: 存下去,所以这一笔只带服务端已经存着的那份 TTS 配置,外加新的 asr_engine。
  const saveAsr = useMutation({
    mutationFn: (next: string) =>
      setAgentVoice({
        engine: pref.data?.engine ?? "",
        engine_voice: pref.data?.engine_voice ?? "",
        engine_voice_resource: pref.data?.engine_voice_resource ?? "",
        engine_model: pref.data?.engine_model ?? "",
        provider_profile_id: pref.data?.provider_profile_id ?? null,
        voice_id: pref.data?.voice_id ?? null,
        speed: pref.data?.speed ?? 1,
        enabled: pref.data?.enabled ?? false,
        asr_engine: next,
        speak_early: pref.data?.speak_early ?? true,
      }),
    onSuccess: (saved) => {
      qc.setQueryData(["agent-voice"], saved);
      rememberSpeechMode(speechModeOf(saved));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  //: 改完即存(和这一页其它几格一样)。空串 = 跟随转写,也是一个要存下去的值。
  //: 水合的那一帧 `asrEngine` 还是初始空串:跳过它,否则每次打开这一页都会把服务端存着的选择清掉。
  const asrHydrated = React.useRef(false);
  React.useEffect(() => {
    if (!hydrated.current) return;
    if (!asrHydrated.current) {
      asrHydrated.current = true;
      return;
    }
    if (asrEngine === savedAsrRef.current) return;
    savedAsrRef.current = asrEngine;
    saveAsr.mutate(asrEngine);
  }, [asrEngine, saveAsr]);

  //: 念法的开关改完即存。它不要求音色已经选好 —— 「先出声」是这一页的偏好,不是一份合成配置;
  //: 只带服务端已经存着的那份 TTS 配置,别把一份没选全的组合顺手存下去。
  const saveSpeakEarly = useMutation({
    mutationFn: (next: boolean) =>
      withRemoteVoiceConsent(() =>
        setAgentVoice({
          engine: pref.data?.engine ?? "",
          engine_voice: pref.data?.engine_voice ?? "",
          engine_voice_resource: pref.data?.engine_voice_resource ?? "",
          engine_model: pref.data?.engine_model ?? "",
          provider_profile_id: pref.data?.provider_profile_id ?? null,
          voice_id: pref.data?.voice_id ?? null,
          speed: pref.data?.speed ?? 1,
          enabled: pref.data?.enabled ?? false,
          asr_engine: pref.data?.asr_engine ?? "",
          speak_early: next,
        }),
      ),
    onSuccess: (saved) => {
      qc.setQueryData(["agent-voice"], saved);
      rememberSpeechMode(speechModeOf(saved));
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const speakEarlyHydrated = React.useRef(false);
  React.useEffect(() => {
    if (!hydrated.current) return;
    if (!speakEarlyHydrated.current) {
      speakEarlyHydrated.current = true;
      return;
    }
    if (speakEarly === savedSpeakEarlyRef.current) return;
    savedSpeakEarlyRef.current = speakEarly;
    saveSpeakEarly.mutate(speakEarly);
  }, [speakEarly, saveSpeakEarly]);

  const enabled = pref.data?.enabled ?? false;
  const ready = Boolean(engine && voice);
  //: 试听念的是**存着的**那份(和对话里真念同一份),所以屏幕上的选择还没落库时先不给点 ——
  //: 否则刚换了音色就点,听到的是换之前那个。改完即存,这段空档只有一个请求那么长。
  const savedVoice = pref.data?.engine_voice || pref.data?.voice_id || "";
  const persisted = pref.data?.engine === engine && savedVoice === voice && pref.data?.speed === speed;

  //: **改完即存,没有保存按钮。** 但存的时机有个条件:换引擎会把音色清空(旧音色在新引擎下
  //: 不存在),那一瞬间的组合是「新引擎 + 空音色」—— 存下去等于存了一份用不了的配置。
  //: 所以只在组合完整时存,而"完整"正好也是它能用的条件。
  const savedRef = React.useRef("");
  React.useEffect(() => {
    if (!hydrated.current || !ready) return;
    const shape = `${engine}|${voice}|${speed}`;
    if (!savedRef.current) {
      // 水合之后的第一次:记下现状,别把服务端刚给的那份再写回去。
      savedRef.current = `${pref.data?.engine ?? ""}|${savedVoice}|${pref.data?.speed ?? 1}`;
    }
    if (shape === savedRef.current) return;
    savedRef.current = shape;
    // 开关原样带上:关着的时候换音色只是改配置,不能顺手把「语音对话」重新打开。
    save.mutate(enabled);
  }, [engine, voice, speed, ready, enabled, pref.data, savedVoice, save]);

  return (
    <SettingsGroup title={t("agentVoiceTitle")} description={t("agentVoiceDesc")}>
      <SettingsRow label={t("agentVoiceEnabled")} description={t("agentVoiceEnabledDesc")}>
        <Switch
          checked={enabled}
          disabled={!ready && !enabled}
          onCheckedChange={(next) => save.mutate(next)}
          aria-label={t("agentVoiceEnabled")}
        />
      </SettingsRow>
      <SettingsRow label={t("agentVoiceSpeakEarly")} description={t("agentVoiceSpeakEarlyDesc")}>
        <Segmented<SpeechMode>
          value={speakEarly ? "early" : "whole"}
          onValueChange={(next) => setSpeakEarly(next === "early")}
          aria-label={t("agentVoiceSpeakEarly")}
          options={[
            { value: "early", label: t("agentVoiceSpeakEarlyEarly") },
            { value: "whole", label: t("agentVoiceSpeakEarlyWhole") },
          ]}
        />
      </SettingsRow>
      <SettingsRow label={t("voiceDockTitle")} description={t("voiceDockDesc")}>
        <Switch checked={voiceDock} onCheckedChange={setVoiceDock} aria-label={t("voiceDockTitle")} />
      </SettingsRow>
      <SettingsRow label={t("agentVoiceEngine")} description={t("agentVoiceEngineDesc")}>
        <Select
          value={engine}
          onValueChange={(next) => {
            setEngine(next);
            // 换引擎就换了一整套音色 id,旧的那个在新引擎下不存在 —— 留着它会发出去一个
            // 对方不认识的值,换回来的是一句看不懂的报错。
            setVoice("");
          }}
        >
          <SelectTrigger className={SETTINGS_FIELD_WIDTH} aria-label={t("agentVoiceEngine")}>
            <SelectValue placeholder={t("agentVoicePickEngine")} />
          </SelectTrigger>
          <SelectContent>
            {(engines.data ?? [])
              // 没就绪的引擎(缺 Key、没装运行环境)列出来只会让人选中之后才失败。
              .filter((one) => one.ready)
              .map((one) => (
                <SelectItem key={one.id} value={one.id} truncate>
                  {one.label}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      </SettingsRow>
      <SettingsRow label={t("agentVoiceVoice")} description={t("agentVoiceVoiceDesc")}>
        <div className="flex items-center gap-1.5">
          {/* 音色目录动辄几十条,超过阈值 OptionPicker 自己换成可搜索的那一版。 */}
          <OptionPicker
            value={voice}
            onChange={setVoice}
            //: 有克隆音色时分两组:系统音色、我的克隆音色(和配音面板同一个分法)。
            options={voiceChoices.map((one) => ({
              ...one,
              ...(hasCloned ? { group: t(one.cloned ? "voiceGroupCloned" : "voiceGroupStock") } : {}),
            }))}
            ariaLabel={t("agentVoiceVoice")}
            placeholder={t("agentVoicePickVoice")}
            className={SETTINGS_FIELD_WIDTH}
          />
          {/* 试听和对话里真念走同一个合成(后端 agent_voice.speak),听到的就是以后念给你的那个声音。
              它只要求选好、不要求开关开着:试听本来就发生在决定打开之前。 */}
          <VoicePreviewButton
            load={() => fetchAgentVoicePreview({ workspace_id: workspaceId, text: t("agentVoiceSample") })}
            disabled={!ready || !persisted}
            disabledReason={t("agentVoicePreviewNeedsVoice")}
          />
        </div>
      </SettingsRow>
      <SettingsRow label={t("agentVoiceSpeed")} description={t("agentVoiceSpeedDesc")}>
        <Select value={String(speed)} onValueChange={(next) => setSpeed(Number(next))}>
          {/* 语速只装得下「1.25×」—— 给它标准宽度等于在一个数字后面拖一条空槽。 */}
        <SelectTrigger className="w-[110px]" aria-label={t("agentVoiceSpeed")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SPEEDS.map((one) => (
              <SelectItem key={one} value={String(one)}>
                {one}×
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </SettingsRow>
      {/* 说话输入(ASR)。放在最后一格:上面几行都是「它念出来是什么声音」,这一行是「你说话时谁在听」。 */}
      <SettingsRow label={t("agentVoiceDictationEngine")} description={t("agentVoiceDictationEngineDesc")}>
        <Select
          value={asrEngine || FOLLOW_TRANSCRIPTION}
          onValueChange={(next) => setAsrEngine(next === FOLLOW_TRANSCRIPTION ? "" : next)}
        >
          <SelectTrigger className={SETTINGS_FIELD_WIDTH} aria-label={t("agentVoiceDictationEngine")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={FOLLOW_TRANSCRIPTION} truncate>
              {t("agentVoiceDictationFollow")}
              {followTranscription ? ` · ${followTranscription}` : ""}
            </SelectItem>
            {dictationChoices.map((one) => (
              <SelectItem key={one.id} value={one.id} truncate>
                {one.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </SettingsRow>
    </SettingsGroup>
  );
}
