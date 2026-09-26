/**
 * AI 生成里**音频**这一种(音乐、BGM、歌曲、音效、给视频配声)的专属控件。
 *
 * 音频走的是和图像、视频同一条生成管线(同一个会话、同一个模型选择器、同一份能力描述符,
 * 见 ADR 0022),只多两样图像和视频没有的东西:
 *
 * - **歌词**:一段长文字,和提示词分开 —— 提示词说「怎么唱」(风格、情绪、乐器),歌词是「唱什么」。
 *   它有自己的上限(`max_lyrics_chars`),而且选了纯音乐就不该有歌词(提交前后端会拦,界面先灰掉)。
 * - **结果是一段声音**:会话里的产出渲染成播放器,不是缩略图。一次可能交回几首(Suno 一次两首),
 *   每一首都要听得到 —— 只放第一首的话,另一首在素材库里躺着,而用户不知道。
 *
 * 「念一段字」(语音合成)不在这里:那是 AI 工作台「音频」页的事,见 AudioWorkspace。
 */
import React from "react";

import { assetFileUrl, type GenerationOption } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Textarea } from "@/components/ui/textarea";
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

/** 会话里一次音频生成的产出:每一首一个播放器,按交回的顺序排。 */
export function GeneratedAudioList({ assetIds, title }: { assetIds: string[]; title: string }) {
  const t = useI18n();
  return (
    <ul className="m-0 grid w-full max-w-[min(560px,100%)] list-none gap-2 p-0" aria-label={t("genAudioResults")}>
      {assetIds.map((assetId, index) => (
        <li key={assetId} className="grid gap-1 rounded-lg border border-border bg-card px-3 py-2">
          <span className="truncate text-ui-xs font-medium text-muted-foreground">
            {assetIds.length > 1 ? `${title} · ${t("genAudioTrack").replace("{n}", String(index + 1))}` : title}
          </span>
          <audio className="block h-9 w-full" src={assetFileUrl(assetId)} controls preload="metadata" />
        </li>
      ))}
    </ul>
  );
}
