import React from "react";
import { assetKeys } from "@/api/queryKeys";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AudioLines, Mic, Settings2, Wand2 } from "lucide-react";
import { toast } from "sonner";

import {api, assetPlaybackUrl, generatePodcast, listTtsEngines, listTtsVoices, synthesizeVoice, synthesizeWithEngine, type Asset, type Job, type Workspace} from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SEGMENTED_LIST, segmentedTriggerClass } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { PODCAST_ENGINE } from "@/features/voice/speechEngines";
import { FIELD, FIELD_SPEED, FieldRow, SpeechVoiceFields, SpeedPicker, VoiceField, VoicePicker } from "@/features/voice/SpeechVoiceFields";
import { useSpeechVoice } from "@/features/voice/useSpeechVoice";
import { useWatchedJob } from "@/features/voice/useWatchedJob";
import { gotoSettings } from "@/lib/deepLink";
import { relativeTime } from "@/lib/time";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";

type AudioMode = "speech" | "podcast";
type PodcastMode = "summarize" | "read" | "research";

//: 两种产物在素材库里的 source —— 「最近生成」据此只列这一页做出来的东西。
const OUTPUT_SOURCE: Record<AudioMode, string> = { speech: "tts", podcast: "podcast" };

/**
 * AI 生成 → 音频:产出**独立的音频素材**,和哪条时间线无关。
 *
 * - 语音:用选定的引擎和声音念一段文字。
 * - 播客:两个发音人把一段材料改写成对话、照读,或联网检索后讨论。
 *
 * 此前两者都挤在剪辑台的「配音」栏里 —— 可它们的产物只是进素材库,不碰时间线;而剪辑台那一栏
 * 真正该做的「给字幕配音」反倒藏在别处。引擎/声音的选择与剪辑台共用 SpeechVoiceFields。
 */
export function AudioWorkspace({ workspace, switcher }: { workspace: Workspace; switcher?: React.ReactNode }) {
  const t = useI18n();
  const [mode, setMode] = usePersistentTab<AudioMode>("ai-studio-audio", "speech", ["speech", "podcast"]);
  // 做完了由任务中心说、由它刷新素材库;这里只管按钮忙不忙。
  const job = useWatchedJob();
  const onQueued = (queued: Job) => {
    toast.message(t("audioGenerating"));
    job.watch(queued.id);
  };

  return (
    <section className="grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] overflow-hidden bg-workspace-panel">
      <div className="flex min-h-14 min-w-0 flex-wrap items-center gap-2 border-b border-divider px-4 py-1.5 max-[821px]:pl-14">
        {switcher}
        <div className={SEGMENTED_LIST} role="tablist" aria-label={t("aiTabAudio")}>
          {(["speech", "podcast"] as const).map((item) => (
            <button
              key={item}
              type="button"
              role="tab"
              aria-selected={mode === item}
              className={segmentedTriggerClass(mode === item)}
              onClick={() => setMode(item)}
            >
              {item === "speech" ? <Mic size={13} /> : <AudioLines size={13} />}
              {t(item === "speech" ? "audioModeSpeech" : "audioModePodcast")}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 overflow-y-auto overflow-x-hidden px-4 py-6">
        <div className="mx-auto grid w-full max-w-[680px] gap-8">
          {mode === "speech" ? (
            <SpeechForm workspace={workspace} busy={job.running} onQueued={onQueued} />
          ) : (
            <PodcastForm workspace={workspace} busy={job.running} onQueued={onQueued} />
          )}
          <RecentAudio workspace={workspace} source={OUTPUT_SOURCE[mode]} />
        </div>
      </div>
    </section>
  );
}

function SpeechForm({ workspace, busy, onQueued }: { workspace: Workspace; busy: boolean; onQueued: (job: Job) => void }) {
  const t = useI18n();
  const voice = useSpeechVoice(workspace.id);
  const [text, setText] = React.useState("");
  const synth = useMutation({
    mutationFn: () => {
      const { engine, voice_id, ...rest } = voice.params;
      return engine === "clone"
        ? synthesizeVoice(voice_id as string, { text, ...rest })
        : synthesizeWithEngine({ workspace_id: workspace.id, text, engine, ...rest });
    },
    onSuccess: (queued) => {
      setText("");
      onQueued(queued);
    },
    onError: (error: Error) => toast.error(error.message),
  });
  // 克隆要先有音色。音色库在设置里管(这一页不绑项目,没有「从说话人提取」的素材可挑)。
  const needsVoice = voice.engine === "clone" && voice.libraryLoaded && voice.library.length === 0;

  return (
    <div className="grid gap-3">
      <SpeechVoiceFields voice={voice} />
      {needsVoice && (
        <SettingsHint body={t("audioCloneNeedsVoice")} action={t("audioManageVoices")} section="dubbing" />
      )}
      <Textarea
        placeholder={t("voiceSynthPlaceholder")}
        value={text}
        rows={5}
        aria-label={t("voiceSynthPlaceholder")}
        onChange={(event) => setText(event.target.value)}
      />
      <Button className="justify-self-end" disabled={!text.trim() || !voice.ready} loading={synth.isPending || busy} onClick={() => synth.mutate()}>
        <Wand2 size={13} /> {t("voiceGenerate")}
      </Button>
    </div>
  );
}

function PodcastForm({ workspace, busy, onQueued }: { workspace: Workspace; busy: boolean; onQueued: (job: Job) => void }) {
  const t = useI18n();
  const engines = useQuery({ queryKey: ["tts-engines"], queryFn: listTtsEngines, staleTime: 30_000 });
  const engine = engines.data?.find((item) => item.id === PODCAST_ENGINE);
  const speakers = useQuery({
    queryKey: ["tts-voices", PODCAST_ENGINE],
    queryFn: () => listTtsVoices(PODCAST_ENGINE),
    enabled: Boolean(engine),
  });
  const choices = speakers.data ?? [];
  const [mode, setMode] = React.useState<PodcastMode>("summarize");
  const [speakerA, setSpeakerA] = React.useState("");
  const [speakerB, setSpeakerB] = React.useState("");
  const [speed, setSpeed] = React.useState(1);
  const [text, setText] = React.useState("");
  // 下拉没选时**显示**的是第一/第二个,那就提交同样的。
  const pair = [speakerA || choices[0]?.value || "", speakerB || choices[1]?.value || ""];
  // 照读一个人就够;改写和讨论是对谈,要两个不同的人。
  const speakersReady = mode === "read" ? Boolean(pair[0]) : pair.every(Boolean) && pair[0] !== pair[1];

  const run = useMutation({
    mutationFn: () =>
      generatePodcast({
        workspace_id: workspace.id,
        mode,
        // 讨论模式谈的是一个主题;另两种从文本本身出发。
        text: mode === "research" ? "" : text,
        topic: mode === "research" ? text : "",
        // 照读时两个人轮流念;目录里只有一个发音人时就一个人念完。
        speakers: pair.filter(Boolean),
        speed,
      }),
    onSuccess: (queued) => {
      setText("");
      onQueued(queued);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  if (engines.isSuccess && (!engine || engine.ready === false)) {
    // 没配好就直说去哪儿配,而不是摆一张点了必然失败的表单。
    return (
      <SettingsHint
        body={engine?.note || t("audioPodcastUnavailable")}
        action={t("audioConfigurePodcast")}
        section="provider-audio"
      />
    );
  }

  return (
    <div className="grid gap-3">
      <FieldRow>
        <VoiceField label={t("voicePodcastMode")} className={FIELD}>
          <Select value={mode} onValueChange={(value) => setMode(value as PodcastMode)}>
            <SelectTrigger className="w-full min-w-0" aria-label={t("voicePodcastMode")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="summarize">{t("voicePodcastSummarize")}</SelectItem>
              <SelectItem value="read">{t("voicePodcastRead")}</SelectItem>
              <SelectItem value="research">{t("voicePodcastResearch")}</SelectItem>
            </SelectContent>
          </Select>
        </VoiceField>
        <VoiceField label={t("voiceSpeed")} className={FIELD_SPEED}>
          <SpeedPicker value={speed} onChange={setSpeed} ariaLabel={t("voiceSpeed")} />
        </VoiceField>
      </FieldRow>
      {choices.length > 0 && (
        <FieldRow>
          <VoiceField label={t("voicePodcastSpeakerA")} className={FIELD}>
            <VoicePicker value={pair[0]} onChange={setSpeakerA} choices={choices} ariaLabel={t("voicePodcastSpeakerA")} />
          </VoiceField>
          <VoiceField label={t("voicePodcastSpeakerB")} className={FIELD}>
            <VoicePicker value={pair[1]} onChange={setSpeakerB} choices={choices} ariaLabel={t("voicePodcastSpeakerB")} />
          </VoiceField>
        </FieldRow>
      )}
      <Textarea
        placeholder={t(mode === "research" ? "audioPodcastTopicPlaceholder" : "audioPodcastTextPlaceholder")}
        aria-label={t(mode === "research" ? "audioPodcastTopicPlaceholder" : "audioPodcastTextPlaceholder")}
        value={text}
        rows={mode === "research" ? 2 : 8}
        onChange={(event) => setText(event.target.value)}
      />
      {!speakersReady && choices.length > 0 && (
        <p className="m-0 text-ui-xs leading-[1.45] text-muted-foreground">{t("voicePodcastNeedTwo")}</p>
      )}
      <Button className="justify-self-end" disabled={!text.trim() || !speakersReady} loading={run.isPending || busy} onClick={() => run.mutate()}>
        <Wand2 size={13} /> {t("voiceGenerate")}
      </Button>
    </div>
  );
}

function SettingsHint({ body, action, section }: { body: string; action: string; section: string }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-dashed border-border px-3 py-2.5 text-ui-xs leading-[1.55] text-muted-foreground">
      <span className="min-w-0 flex-1">{body}</span>
      <Button size="sm" variant="outline" onClick={() => gotoSettings(section)}>
        <Settings2 size={12} /> {action}
      </Button>
    </div>
  );
}

/** 这一页做出来的最近几条,就地试听。完整的在素材库里。 */
function RecentAudio({ workspace, source }: { workspace: Workspace; source: string }) {
  const t = useI18n();
  const { locale } = usePreferences();
  // 与素材库同一个缓存键:那边导入/删除,这里跟着变;这里生成完一刷,那边也有。
  const assets = useQuery({
    queryKey: assetKeys.list(workspace.id),
    queryFn: () => api<Asset[]>(`/api/assets?workspace_id=${workspace.id}`),
  });
  const recent = (assets.data ?? [])
    .filter((asset) => asset.kind === "audio" && asset.source === source)
    .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""))
    .slice(0, 12);

  return (
    <section className="grid gap-2" aria-label={t("audioRecentTitle")}>
      <h3 className="m-0 text-ui-xs font-semibold text-muted-foreground">{t("audioRecentTitle")}</h3>
      {assets.isSuccess && recent.length === 0 && (
        <p className="m-0 text-ui-xs text-muted-foreground">{t("audioRecentEmpty")}</p>
      )}
      <ul className="m-0 grid list-none divide-y divide-border p-0">
        {recent.map((asset) => (
          <li key={asset.id} className="grid gap-1.5 py-2.5">
            <div className="flex min-w-0 items-baseline justify-between gap-3">
              <span className="min-w-0 truncate text-ui-sm" title={asset.name}>
                {asset.name}
              </span>
              {asset.created_at && (
                <span className={cn("shrink-0 text-ui-2xs text-muted-foreground tabular-nums")}>
                  {relativeTime(asset.created_at, locale)}
                </span>
              )}
            </div>
            <audio className="h-8 w-full" controls preload="none" src={assetPlaybackUrl(asset.id)} />
          </li>
        ))}
      </ul>
    </section>
  );
}
