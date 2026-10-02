import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Type } from "lucide-react";
import { toast } from "sonner";

import { downloadF5Model, dubSubtitles, listF5Models, ORIGINAL_AUDIO_MODES, type OriginalAudio, type Sequence } from "@/api/client";
import { useIsDeploymentAdmin } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { NONE, optionalValue } from "@/components/ui/selectSentinel";
import { Switch } from "@/components/ui/switch";
import { detectScript, dubTextOf, hasVoiceFor, pickVoiceFor, unspeakable } from "@/features/editor/dubLanguage";
import { VoiceField } from "@/features/voice/SpeechVoiceFields";
import type { SpeechVoice } from "@/features/voice/useSpeechVoice";
import { useWatchedJob } from "@/lib/useWatchedJob";
import { formatBytes } from "@/lib/bytes";
import { useEditorStore } from "@/features/editor/editorStore";
import { CLONE_ENGINE, DEFAULT_MATCH_DURATION } from "@/api/domains/speech";
import { formatTimecode } from "@/lib/time";

type Line = "all" | "first" | "last";

/**
 * 给时间线上的字幕配音:字幕 → 逐条合成 → 落到一条新的音频轨。
 *
 * 「用哪个引擎、哪个声音」不在这里 —— 那是 SpeechVoiceFields,和它共用一份状态。这里只管
 * 字幕特有的:配哪条轨、配哪几条、双语念哪一行、要不要拉到段落长度、这段文字这个引擎念不念得了。
 *
 * **一次只配一条字幕轨。** 双语字幕分成两条轨时(原文一条、译文一条),此前这里把所有字幕轨的条目
 * 一股脑交下去,同一秒上一句念原文、一句念译文。有多条时摆一个选择,默认最下面那条(先有的原文轨);
 * 时间线上选中了哪条轨的字幕,就默认那条。后端也拒绝跨轨的一批(subtitle_dub.start_subtitle_dub)。
 *
 * **字幕列表行内的配音按钮只配那一条**(`focusClipId`),不去改时间线上的选中 —— 选中是全局的,
 * 借它传「配哪一条」会顺手把用户在时间线上框好的东西冲掉。
 */
export function SubtitleDub({
  sequence,
  voice,
  onOpenSubtitles,
  focusClipId,
  onClearFocus,
}: {
  sequence: Sequence;
  voice: SpeechVoice;
  onOpenSubtitles?: () => void;
  /** 只配这一条(字幕列表行内的配音按钮)。 */
  focusClipId?: string | null;
  onClearFocus?: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const subtitleTracks = React.useMemo(
    () => (sequence.tracks ?? []).filter((track) => track.kind === "subtitle").sort((a, b) => a.position - b.position),
    [sequence],
  );
  const subtitles = React.useMemo(
    () => subtitleTracks.flatMap((track) => track.clips ?? []).sort((a, b) => a.timeline_start - b.timeline_start),
    [subtitleTracks],
  );
  const selectedClipIds = useEditorStore((state) => state.selectedClipIds);
  const focused = focusClipId ? subtitles.find((clip) => clip.id === focusClipId) ?? null : null;
  //: 默认配哪条轨:选中的字幕在哪条轨上就是哪条,否则最下面那条。用户挑过就听他的。
  const [pickedTrackId, setPickedTrackId] = React.useState<string>("");
  const selectedTrackId = subtitles.find((clip) => selectedClipIds.includes(clip.id))?.track_id;
  const trackId = subtitleTracks.some((track) => track.id === pickedTrackId)
    ? pickedTrackId
    : (selectedTrackId ?? subtitleTracks[0]?.id ?? "");
  const onTrack = subtitles.filter((clip) => clip.track_id === trackId);
  const selected = onTrack.filter((clip) => selectedClipIds.includes(clip.id));
  const [selectedOnly, setSelectedOnly] = React.useState(true);
  const pool = focused ? [focused] : selectedOnly && selected.length > 0 ? selected : onTrack;
  const targets = pool.filter((clip) => (clip.text_override ?? "").trim());

  // 双语字幕是「原文\n译文」两行。整段念 = 先念原文再念译文,一条 3 秒的字幕配出 12 秒的音。
  // 默认全念(单语字幕就该全念),真有多行时才把这个选择摆出来。
  const [line, setLine] = React.useState<Line>("all");
  const hasBilingual = targets.some((clip) => (clip.text_override ?? "").trim().includes("\n"));
  // 匹配段落长度的默认值和后端一处(subtitle_dub.DEFAULT_MATCH_DURATION):开。变速夹在 0.9–1.5 倍,
  // 念出来仍是人话;此前这里默认关、智能体和工作流默认开,同一条时间线两个入口配出来不一样。
  const [matchDuration, setMatchDuration] = React.useState(DEFAULT_MATCH_DURATION);
  const [originalAudio, setOriginalAudio] = React.useState<OriginalAudio>("duck");
  //: 用哪份 F5 权重。空 = 按文字自动挑 —— 中日韩俄阿印能认出来,而法德西意芬都写拉丁字母,
  //: 没有任何字符能证明"这是法语而不是英语",只能由用户明说。
  const [weights, setWeights] = React.useState(NONE);
  const usesF5 = voice.engine === CLONE_ENGINE && voice.cloneEngine === "f5-tts";
  const f5Models = useQuery({
    queryKey: ["f5-models"],
    queryFn: listF5Models,
    enabled: usesF5,
    // 下载中就跟着刷:点完下载不该盯着一个不动的界面猜它有没有在跑。
    refetchInterval: (query) => (query.state.data?.some((item) => item.status === "downloading") ? 1500 : false),
  });
  const installedWeights = usesF5 ? (f5Models.data ?? []).filter((model) => model.installed) : [];

  const texts = targets.map((clip) => dubTextOf(clip, line));
  const wantScript = detectScript(texts.join("\n"));
  // 能念这段文字、但还没下的那份权重 —— 有它就把「下载」直接摆在这儿,不让人去管理页找。
  // 下载只给部署管理员(routes/voices.download_f5_model),成员这里只被告知由谁来下。
  const isAdmin = useIsDeploymentAdmin();
  const missingModel = usesF5
    ? (f5Models.data ?? []).find((model) => wantScript && (model.languages ?? []).includes(wantScript) && !model.installed)
    : undefined;
  const downloadModel = useMutation({
    mutationFn: (modelId: string) => downloadF5Model(modelId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["f5-models"] }),
    onError: (error: Error) => toast.error(error.message),
  });

  // **默认就选对**:用户还没亲手挑过发音人时,按字幕的文字挑一个念得了的。挑过就不再覆盖。
  const { engine, engineVoiceChoice, voiceChoices, setEngineVoice } = voice;
  React.useEffect(() => {
    if (engine === CLONE_ENGINE || engineVoiceChoice || voiceChoices.length === 0) return;
    const match = pickVoiceFor(wantScript, engine, voiceChoices);
    if (match) setEngineVoice(match);
  }, [engine, engineVoiceChoice, voiceChoices, wantScript, setEngineVoice]);

  // 语言对不上时引擎**不会报错**,它按自己的发音规则硬念一遍。后端也会拦,但那是排队之后;
  // 文本就在眼前,这一刻就该说。
  // 克隆能念什么是 **F5 权重**的属性;Fish Speech 一份模型念多语,不拿 F5 的清单去判它。
  // 权重清单还没到时也不判 —— 空清单会把每一种语言都说成念不了。
  const mismatch =
    engine === CLONE_ENGINE && (!usesF5 || !f5Models.isSuccess)
      ? ""
      : unspeakable(
          texts,
          engine,
          engine === CLONE_ENGINE ? "" : voice.engineVoice,
          installedWeights.flatMap((model) => model.languages ?? []),
        );
  const langName = mismatch ? t(`langName_${mismatch}` as never) : "";

  // 配好了没有、时间线和素材库的刷新,都归任务中心(ADR-0018);这里只管按钮忙不忙。
  const job = useWatchedJob();
  const run = useMutation({
    mutationFn: () =>
      dubSubtitles(sequence, {
        ...voice.params,
        clip_ids: targets.map((clip) => clip.id),
        track_id: focused ? focused.track_id : trackId,
        match_duration: matchDuration,
        line,
        original_audio: originalAudio,
        ...(usesF5 ? { clone_model: optionalValue(weights) ?? "" } : {}),
      }),
    onSuccess: (queued) => {
      job.watch(queued.id);
      // 只确认"排上了",不假装已经配好 —— 配好由任务中心说。
      toast.success(t("subtitleDubQueued").replace("{n}", String(targets.length)));
    },
    onError: (error: Error) => toast.error(t("subtitleDubFailed"), { description: error.message }),
  });

  if (subtitles.length === 0) {
    return (
      <div className="grid justify-items-start gap-2 rounded-md border border-dashed border-border px-3 py-3 text-ui-xs leading-[1.55] text-muted-foreground">
        <span>{t("subtitleDubEmpty")}</span>
        {onOpenSubtitles && (
          <Button size="sm" variant="outline" onClick={onOpenSubtitles}>
            <Type size={12} /> {t("subtitleDubOpenSubtitles")}
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="grid gap-3">
      {installedWeights.length > 1 && (
        <VoiceField label={t("subtitleDubWeights")}>
          <Select value={weights} onValueChange={setWeights}>
            <SelectTrigger className="w-full min-w-0" aria-label={t("subtitleDubWeights")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {/* 「自动」排第一:中日韩俄阿印能按文字认出来,那是绝大多数情况。 */}
              <SelectItem value={NONE}>{t("subtitleDubWeightsAuto")}</SelectItem>
              {installedWeights.map((model) => (
                <SelectItem key={model.id} value={model.id}>
                  {model.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </VoiceField>
      )}
      {/* 只在真有双语字幕时出现 —— 单语字幕摆一个「念哪一行」只会让人以为自己漏配了什么。 */}
      {hasBilingual && (
        <VoiceField label={t("subtitleDubLine")}>
          <Select value={line} onValueChange={(next) => setLine(next as Line)}>
            <SelectTrigger className="w-full min-w-0" aria-label={t("subtitleDubLine")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("subtitleDubLineAll")}</SelectItem>
              <SelectItem value="first">{t("subtitleDubLineFirst")}</SelectItem>
              <SelectItem value="last">{t("subtitleDubLineLast")}</SelectItem>
            </SelectContent>
          </Select>
        </VoiceField>
      )}
      {focused ? (
        <div className="flex items-center justify-between gap-2 rounded-md border border-border px-2 py-1.5 text-ui-xs">
          <span className="min-w-0 truncate">
            {t("subtitleDubFocused").replace("{time}", formatTimecode(focused.timeline_start))}
          </span>
          {onClearFocus && (
            <Button size="sm" variant="ghost" onClick={onClearFocus}>
              {t("subtitleDubFocusClear")}
            </Button>
          )}
        </div>
      ) : (
        subtitleTracks.length > 1 && (
          <VoiceField label={t("subtitleDubTrack")}>
            <Select value={trackId} onValueChange={setPickedTrackId}>
              <SelectTrigger className="w-full min-w-0" aria-label={t("subtitleDubTrack")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {subtitleTracks.map((track) => (
                  <SelectItem key={track.id} value={track.id}>
                    {track.name} · {t("subtitleDubTrackCount").replace("{n}", String((track.clips ?? []).length))}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </VoiceField>
        )
      )}
      <VoiceField label={t("subtitleDubOriginal")}>
        <Select value={originalAudio} onValueChange={(next) => setOriginalAudio(next as OriginalAudio)}>
          <SelectTrigger className="w-full min-w-0" aria-label={t("subtitleDubOriginal")} title={t("subtitleDubOriginalHint")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ORIGINAL_AUDIO_MODES.map((mode) => (
              <SelectItem key={mode} value={mode}>{t(`subtitleDubOriginal_${mode}`)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </VoiceField>
      <div className="grid gap-2 text-ui-xs text-muted-foreground">
        {!focused && selected.length > 0 && (
          <label className="flex items-center justify-between gap-2">
            <span>{t("subtitleTranslateSelectedOnly").replace("{n}", String(selected.length))}</span>
            <Switch checked={selectedOnly} onCheckedChange={setSelectedOnly} />
          </label>
        )}
        <label className="flex items-center justify-between gap-2">
          <span title={t("subtitleDubMatchHint")}>{t("subtitleDubMatch")}</span>
          <Switch checked={matchDuration} onCheckedChange={setMatchDuration} />
        </label>
      </div>
      {mismatch && (
        <div className="rounded-md border border-[color-mix(in_srgb,var(--destructive)_35%,var(--border))] bg-[color-mix(in_srgb,var(--destructive)_8%,transparent)] px-2 py-1.5 text-ui-2xs leading-[1.5] text-foreground">
          {/* 说清楚**下一步动哪儿**:这个引擎里有能念的发音人就让他换发音人 —— 已经选对引擎
              却被告知「换引擎」,只会让人以为这个引擎不行。 */}
          {missingModel
            ? // 同一个占位符出现两次,replace 只换第一个 —— 界面上会留一个字面的 {lang}(真出过)。
              t("subtitleDubModelMissing")
                .replaceAll("{lang}", langName)
                .replace("{size}", (missingModel.expected_bytes / 1_000_000_000).toFixed(1))
            : hasVoiceFor(mismatch, engine, voiceChoices)
              ? t("subtitleDubLangVoice").replaceAll("{lang}", langName)
              : t("subtitleDubLangEngine").replaceAll("{lang}", langName)}
          {missingModel && !isAdmin && (
            <span className="mt-1 block text-muted-foreground">{t("engineInstalledByAdmin")}</span>
          )}
          {missingModel && isAdmin && (
            <Button
              size="sm"
              variant="outline"
              className="mt-1.5 w-full"
              loading={downloadModel.isPending || missingModel.status === "downloading"}
              onClick={() => downloadModel.mutate(missingModel.id)}
            >
              {/* 权重 1.3–5.4 GB,慢网络下一个百分点要好几分钟 —— 有实测总量就一并报出来,
                  否则"看不出还要多久"和"卡住了"在用户眼里是同一件事。 */}
              {missingModel.status === "downloading"
                ? missingModel.total_bytes > 0
                  ? t("subtitleDubModelDownloadingSize")
                      .replace("{n}", String(Math.round(missingModel.progress * 100)))
                      .replace("{done}", formatBytes(missingModel.downloaded_bytes))
                      .replace("{total}", formatBytes(missingModel.total_bytes))
                  : t("subtitleDubModelDownloading").replace("{n}", String(Math.round(missingModel.progress * 100)))
                : t("subtitleDubModelDownload")}
            </Button>
          )}
        </div>
      )}
      <Button
        className="w-full"
        disabled={targets.length === 0 || !voice.ready}
        loading={run.isPending || job.running}
        onClick={() => run.mutate()}
      >
        <AudioLines size={13} /> {t("subtitleDubApply").replace("{n}", String(targets.length))}
      </Button>
      <p className="m-0 text-ui-2xs leading-[1.5] text-muted-foreground">{t("subtitleDubTrackNote")}</p>
    </div>
  );
}
