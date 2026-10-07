/**
 * AI 生成里**音频**这一种(音乐、BGM、歌曲、音效、给视频配声)的专属控件。
 *
 * 音频走的是和图像、视频同一条生成管线(同一个会话工作台、同一份能力描述符,见 ADR 0022),只是不在
 * 同一页:它在 AI 工作台「音频」页的「音乐与音效」(见 AudioWorkspace 与 GenerateWorkspace 的 `medium`)。
 * 比图像和视频多两样东西:
 *
 * - **歌词**:一段长文字,和提示词分开 —— 提示词说「怎么唱」(风格、情绪、乐器),歌词是「唱什么」。
 *   它有自己的上限(`max_lyrics_chars`),而且选了纯音乐就不该有歌词(提交前后端会拦,界面先灰掉)。
 * - **结果是一段声音**:会话里的产出渲染成播放器,不是缩略图。一次可能交回几首(Suno 一次两首),
 *   每一首都要听得到 —— 只放第一首的话,另一首在素材库里躺着,而用户不知道。
 *
 * 「念一段字」(语音合成)不在这里:那是「音频」页的「朗读」,见 AudioWorkspace。
 */
import React from "react";
import { Download, FolderOpen, Pause, Play, Volume2, VolumeX } from "lucide-react";

import { assetFileUrl, type GenerationOption } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { mediaClock, usePlayback, useWaveformPeaks, WaveformScrubber } from "@/components/app/media-playback";
import { IconButton } from "@/components/ui/icon-button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Truncate } from "@/components/ui/truncate";
import { takePlayback } from "@/lib/audioPlayback";
import { gotoAsset } from "@/lib/deepLink";
import { saveAssetToDisk } from "@/lib/download";
import { capabilityNumber, supportsParameter } from "@/lib/generationCapabilities";
import { cn } from "@/lib/utils";

/** 音频模型能挂的输入素材,按在面板上出现的顺序:要配声的视频、参考音频、图生音乐的图。 */
export const AUDIO_SOURCE_ROLES = ["source_video", "reference_audio", "reference_image"] as const;
export type AudioSourceRole = (typeof AUDIO_SOURCE_ROLES)[number];

/** 同一个角色在音频模型上说的是另一件事(例:待编辑的视频 → 要配声的视频),提示语跟着换。 */
export const AUDIO_SOURCE_HINTS: Record<AudioSourceRole, MessageKey> = {
  source_video: "genAudioSourceVideoHint",
  reference_audio: "genAudioReferenceAudioHint",
  reference_image: "genAudioReferenceImageHint",
};

/** 这个音频模型挂得了哪几种素材。 */
export function audioSourceRoles(model: GenerationOption | null): AudioSourceRole[] {
  if (model?.kind !== "audio") return [];
  return AUDIO_SOURCE_ROLES.filter((role) => supportsParameter(model, role));
}

/** 歌词最多几个字;描述符没说就是 0(不限,由后端和供应商把关)。 */
export function lyricsLimit(model: GenerationOption | null): number {
  return capabilityNumber(model, "max_lyrics_chars", 0);
}

/** 歌词编辑器:一个够高的文本框,带字数与上限;选了纯音乐时灰掉并说明为什么。 */
export function LyricsField({
  value,
  onChange,
  limit,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  limit: number;
  disabled: boolean;
}) {
  const t = useI18n();
  const count = value.length;
  const over = limit > 0 && count > limit;
  return (
    <div className="grid gap-1.5">
      <Textarea
        aria-label={t("genLyrics")}
        rows={8}
        className="min-h-40 resize-y bg-field font-mono text-ui-sm leading-[1.6]"
        placeholder={t("genLyricsPlaceholder")}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
      <div className="flex items-start justify-between gap-2 text-ui-2xs leading-[1.45] text-muted-foreground">
        <span>{disabled ? t("genLyricsInstrumentalHint") : t("genLyricsHint")}</span>
        <span className={cn("shrink-0 tabular-nums", over && "font-semibold text-destructive")} aria-live="polite">
          {limit > 0 ? `${count} / ${limit}` : count}
        </span>
      </div>
    </div>
  );
}

/** 一首的波形抽成多少根竖条。卡片最宽 560px,一根 4px 一档,够看出起伏,又不至于密成一片。 */
const WAVEFORM_BARS = 96;

/**
 * 会话里一次音频生成的产出:每一首一张卡,按交回的顺序排(Suno 一次两首,ComfyUI 一张工作流几个保存节点)。
 *
 * **不用原生 `<audio controls>`**(棘轮见 design/nativeControls):那条控件各家浏览器各一个样子、不吃主题,深色界面里
 * 压进来一条亮条(维护者:「太丑了」)。卡片用全站同一套播放机件(components/app/media-playback 的 usePlayback 与
 * 波形进度条):播 / 停、波形上点哪儿跳哪儿、放到哪儿 / 多长、静音,另有保存到本地、在素材库里打开。
 * 同一时刻只响一首(lib/audioPlayback):点第二首,第一首停。
 */
export function GeneratedAudioList({ assetIds, title }: { assetIds: string[]; title: string }) {
  const t = useI18n();
  return (
    <ul className="m-0 grid w-full max-w-[min(560px,100%)] list-none gap-2 p-0" aria-label={t("genAudioResults")}>
      {assetIds.map((assetId, index) => (
        <li key={assetId}>
          <AudioTrack
            assetId={assetId}
            title={title}
            track={assetIds.length > 1 ? t("genAudioTrack").replace("{n}", String(index + 1)) : ""}
          />
        </li>
      ))}
    </ul>
  );
}

/** 卡片的外形:生成中的占位(PendingAudioList)和成品同一个壳,出结果时原地换掉、版面不跳。 */
const TRACK_CARD = "grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 rounded-lg border border-border bg-card py-2.5 pl-2.5 pr-2";

function AudioTrack({ assetId, title, track }: { assetId: string; title: string; track: string }) {
  const t = useI18n();
  const ref = React.useRef<HTMLAudioElement | null>(null);
  const { playing, muted, at, total, error, setTotal, toggle, toggleMute, bind } = usePlayback(ref);
  const peaks = useWaveformPeaks(assetId, WAVEFORM_BARS);
  //: 开始响就接管「当前在响的那一段」(别的音频、试听、朗读先停);自己停了就让出来
  const release = React.useRef<(() => void) | null>(null);
  React.useEffect(() => () => release.current?.(), []);
  return (
    <div className={TRACK_CARD} data-audio-track={assetId}>
      <audio
        ref={ref}
        src={assetFileUrl(assetId)}
        preload="metadata"
        className="hidden"
        onLoadedMetadata={(event) => setTotal(event.currentTarget.duration)}
        {...bind}
        onPlay={() => {
          bind.onPlay();
          release.current?.();
          release.current = takePlayback(() => ref.current?.pause());
        }}
        onPause={() => {
          bind.onPause();
          release.current?.();
          release.current = null;
        }}
      />
      <IconButton
        variant="default"
        size="icon"
        className="row-span-2 rounded-full"
        label={t(playing ? "boardPause" : "boardPlay")}
        onClick={toggle}
      >
        {playing ? <Pause size={14} fill="currentColor" /> : <Play size={14} className="translate-x-px" fill="currentColor" />}
      </IconButton>
      <div className="flex min-w-0 items-center gap-1">
        <Truncate className="min-w-0 flex-1 text-ui-sm font-medium text-foreground">
          {track ? `${title} · ${track}` : title}
        </Truncate>
        <IconButton size="icon-xs" label={t(muted ? "boardUnmute" : "boardMute")} onClick={toggleMute}>
          {muted ? <VolumeX size={13} /> : <Volume2 size={13} />}
        </IconButton>
        <IconButton size="icon-xs" label={t("assetSaveLocal")} onClick={() => saveAssetToDisk({ id: assetId, name: title, original_filename: "" })}>
          <Download size={13} />
        </IconButton>
        <IconButton size="icon-xs" label={t("documentOpenAsset")} onClick={() => gotoAsset(assetId)}>
          <FolderOpen size={13} />
        </IconButton>
      </div>
      <div className="flex min-w-0 items-center gap-2.5 pr-1">
        <WaveformScrubber media={ref} peaks={peaks} at={at} total={total} className="h-8 min-w-0 flex-1" />
        <span className="timecode shrink-0 text-ui-2xs tabular-nums text-muted-foreground">
          {error ? t("mediaPlaybackError") : `${mediaClock(at)} / ${mediaClock(total)}`}
        </span>
      </div>
    </div>
  );
}

/**
 * 还在生成的那几首:和成品卡**同一个壳**(播放键的圆、标题条、一排波形),全是扫光占位 —— 出结果时原地换掉。
 * 排队时不扫光(还没开始做),只摆淡淡的壳子。
 */
export function PendingAudioList({ count, running }: { count: number; running: boolean }) {
  return (
    <ul className="m-0 grid w-full max-w-[min(560px,100%)] list-none gap-2 p-0" aria-hidden>
      {Array.from({ length: Math.max(1, count) }, (_, index) => (
        <li key={index} className={cn(TRACK_CARD, !running && "bg-[color-mix(in_srgb,var(--primary)_4%,var(--card))]")}>
          {running ? <Skeleton className="row-span-2 size-9 rounded-full" /> : <span className="row-span-2 size-9 rounded-full border border-dashed border-border" />}
          <div className="flex h-7 items-center">
            {running ? <Skeleton className="h-3 w-2/5 rounded-full" /> : <span className="h-3 w-2/5 rounded-full bg-muted" />}
          </div>
          <div className="flex h-8 items-center gap-[3px] pr-1">
            {PENDING_WAVE.map((height, bar) =>
              running ? (
                <Skeleton key={bar} className="w-[3px] flex-1 rounded-full" style={{ height: `${height}%` }} />
              ) : (
                <span key={bar} className="w-[3px] flex-1 rounded-full bg-muted" style={{ height: `${height}%` }} />
              ),
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

/** 占位里那排竖条的高低(百分比):一段固定的起伏,不是真波形 —— 看着像一段声音就够了。 */
const PENDING_WAVE = Array.from({ length: 48 }, (_, index) => Math.round(28 + 52 * Math.abs(Math.sin(index * 0.55) * Math.cos(index * 0.17))));
