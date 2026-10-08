/**
 * 语音对话用哪个音色。
 *
 * **和配音的默认音色是两份配置,而这一节存在的理由就是那句话。** 配音要质量:本地零样本
 * 引擎、克隆出来的音色,首次加载十几分钟也认,因为那段音频要进成片。对话要延迟:说完一句
 * 等一分钟就不叫对话了。同一个默认同时服务这两件事,必然在某一边是错的。
 *
 * 引擎与音色的清单**问的是同一组接口**(listTtsEngines / listTtsVoices),和配音面板同源 ——
 * 这里只是另一处选择,不是另一份目录。
 */

import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { fetchAgentVoicePreview, getAgentVoice, listTtsEngines, listTtsVoices, setAgentVoice } from "@/api/client";
import { voiceKeys } from "@/api/queryKeys";
import { useI18n, usePreferences } from "@/app/preferences";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { OptionPicker } from "@/components/ui/option-picker";
import { Switch } from "@/components/ui/switch";
import { SETTINGS_FIELD_WIDTH, SettingsGroup, SettingsRow } from "@/components/settings/settings-layout";
import { VoicePreviewButton } from "@/components/app/VoicePreviewButton";
import { isConsentDeclined, withRemoteVoiceConsent } from "@/features/voice/remoteVoiceConsent";

const SPEEDS = [0.75, 1, 1.25, 1.5, 2];

export function AgentVoiceSection({ workspaceId }: { workspaceId: string }) {
  const t = useI18n();
  const { voiceDock, setVoiceDock } = usePreferences();
  const qc = useQueryClient();
  const pref = useQuery({ queryKey: ["agent-voice"], queryFn: getAgentVoice });
  const engines = useQuery({ queryKey: ["tts-engines"], queryFn: listTtsEngines, staleTime: 30_000 });

  const [engine, setEngine] = React.useState("");
  const [voice, setVoice] = React.useState("");
  const [speed, setSpeed] = React.useState(1);
  // 服务端那份到了之后水合一次。**之后不再回灌** —— 否则用户改了一半会被一次后台刷新盖掉。
  const hydrated = React.useRef(false);
  React.useEffect(() => {
    if (hydrated.current || !pref.data) return;
    hydrated.current = true;
    setEngine(pref.data.engine);
    //: 音色那一格:引擎自己的,或者(CosyVoice)配音库里的一把嗓子 —— 存在 voice_id 上(ADR 0037)。
    setVoice(pref.data.engine_voice || pref.data.voice_id || "");
    setSpeed(pref.data.speed || 1);
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
        }),
      ),
    // 回包就是存下的那份:直接放进缓存,试听键不必等一次重新拉取才知道「屏幕上的已经存好了」。
    onSuccess: (saved) => qc.setQueryData(["agent-voice"], saved),
    onError: (error: Error) => {
      //: 不同意上传:这把嗓子没存上,屏幕上也别留着它(像是选好了),清掉让人重挑。
      if (isConsentDeclined(error)) setVoice("");
      else toast.error(error.message);
    },
  });

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
    </SettingsGroup>
  );
}
