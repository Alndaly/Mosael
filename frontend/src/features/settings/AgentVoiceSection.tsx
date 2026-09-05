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
import { Volume2 } from "lucide-react";
import { toast } from "sonner";

import { getAgentVoice, listTtsEngines, listTtsVoices, setAgentVoice } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { SettingsGroup, SettingsRow } from "@/features/settings/ui";
import { SpeakButton } from "@/components/agent/SpeakButton";

const SPEEDS = [0.75, 1, 1.25, 1.5, 2];

export function AgentVoiceSection({ workspaceId }: { workspaceId: string }) {
  const t = useI18n();
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
    setVoice(pref.data.engine_voice);
    setSpeed(pref.data.speed || 1);
  }, [pref.data]);

  const voices = useQuery({
    queryKey: ["tts-voices", engine],
    queryFn: () => listTtsVoices(engine),
    enabled: Boolean(engine),
  });
  const voiceChoices = voices.data ?? [];
  const chosen = voiceChoices.find((one) => one.value === voice);

  const save = useMutation({
    mutationFn: (enabled: boolean) =>
      setAgentVoice({
        engine,
        engine_voice: voice,
        engine_voice_resource: chosen?.resource_id ?? "",
        engine_model: "",
        provider_profile_id: null,
        voice_id: null,
        speed,
        enabled,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agent-voice"] }),
    onError: (error: Error) => toast.error(error.message),
  });

  const enabled = pref.data?.enabled ?? false;
  const ready = Boolean(engine && voice);

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
          <SelectTrigger className="w-[200px]" aria-label={t("agentVoiceEngine")}>
            <SelectValue placeholder={t("agentVoicePickEngine")} />
          </SelectTrigger>
          <SelectContent>
            {(engines.data ?? [])
              // 没就绪的引擎(缺 Key、没装运行环境)列出来只会让人选中之后才失败。
              .filter((one) => one.ready)
              .map((one) => (
                <SelectItem key={one.id} value={one.id}>
                  {one.label}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      </SettingsRow>
      <SettingsRow label={t("agentVoiceVoice")} description={t("agentVoiceVoiceDesc")}>
        <div className="flex items-center gap-1.5">
          <Select value={voice} onValueChange={setVoice} disabled={!engine}>
            <SelectTrigger className="w-[200px]" aria-label={t("agentVoiceVoice")}>
              <SelectValue placeholder={t("agentVoicePickVoice")} />
            </SelectTrigger>
            <SelectContent>
              {voiceChoices.map((one) => (
                <SelectItem key={one.value} value={one.value}>
                  {one.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {/* 试听走的是**和播放按钮同一条路**,所以听到的就是它以后念给你的那个声音 ——
              另写一条试听接口的话,试听好听、真用起来不是它,而这种不一致最难查。 */}
          {enabled && ready && <SpeakButton text={t("agentVoiceSample")} workspaceId={workspaceId} />}
        </div>
      </SettingsRow>
      <SettingsRow label={t("agentVoiceSpeed")} description={t("agentVoiceSpeedDesc")}>
        <Select value={String(speed)} onValueChange={(next) => setSpeed(Number(next))}>
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
      {/* 显式的保存:引擎、音色、语速是一组要一起生效的选择,逐项即存会在中间态发出
          "这个引擎 + 那个引擎的音色"这种组合。 */}
      <div className="flex justify-end px-1 pb-1 !border-t-0">
        <Button size="sm" disabled={!ready} loading={save.isPending} onClick={() => save.mutate(enabled || ready)}>
          <Volume2 size={13} /> {t("agentVoiceSave")}
        </Button>
      </div>
    </SettingsGroup>
  );
}
