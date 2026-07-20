import React from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Languages, Loader2, MessageSquareText, Mic, Scissors, Sparkles, Split, SplitSquareVertical, Trash2, X } from "lucide-react";

import { API_BASE, fetchJob, getAuthToken, transcribeAsset, type Sequence } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { formatTimecode } from "@/domain/timeline/geometry";
import {
  detectSilences,
  isFillerToken,
  projectTranscript,
  type SegmentLike,
} from "@/domain/timeline/transcriptProjection";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TRANSLATE_LANGS } from "@/features/editor/subtitleStyle";
import { useEditorStore } from "@/stores/editorStore";

type TranscriptOut = components["schemas"]["TranscriptOut"];

export interface CutRange {
  srcStart: number;
  srcEnd: number;
}

/** Selected word key → its cut payload. */
type TokenSelection = Map<string, { clipId: string; srcStart: number; srcEnd: number }>;

/** 老版 chunk-list 的说话人配色:名字哈希到色相,同一说话人永远同色。 */
function speakerHue(speaker: string): number {
  let hash = 0;
  for (const ch of speaker) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return hash % 360;
}

export function TranscriptPanel({
  sequence,
  onCutSegment,
  onCutRanges,
  onSplitPoints,
  onTranslateToSubtitles,
  translating,
}: {
  sequence: Sequence;
  onCutSegment: (clipId: string, srcStart: number, srcEnd: number) => void;
  /** Generate the subtitle track from this transcript, translated into `lang` on the way.
      The transcript is a read-only projection of the clips, so a translation has no home
      here — the subtitle track is where it belongs, and this produces it in one step. */
  onTranslateToSubtitles?: (lang: string) => void;
  translating?: boolean;
  onCutRanges?: (cuts: Array<{ clipId: string; ranges: CutRange[] }>) => void;
  // Split (not remove) the named clips at these source-time points → 按句切分 / 单句独立 / 切一刀.
  onSplitPoints?: (cuts: Array<{ clipId: string; srcTimes: number[] }>) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const playhead = useEditorStore((state) => state.playhead);
  const [selected, setSelected] = React.useState<TokenSelection>(new Map());
  const [showSilences, setShowSilences] = React.useState(false);
  const [translateOpen, setTranslateOpen] = React.useState(false);
  const [lang, setLang] = React.useState("zh-CN");
  const [asrJobId, setAsrJobId] = React.useState<string | null>(null);
  const [asrError, setAsrError] = React.useState<string | null>(null);

  // 逐字稿覆盖 V1(主叙事画面)加所有音轨(口播/旁白常在 A1)。
  const videoClips = React.useMemo(() => {
    const tracks = sequence.tracks ?? [];
    const mainVideo = tracks.find((item) => item.kind === "video");
    const audioTracks = tracks.filter((item) => item.kind === "audio");
    return [...(mainVideo?.clips ?? []), ...audioTracks.flatMap((track) => track.clips ?? [])];
  }, [sequence]);
  const assetIds = React.useMemo(
    () => [...new Set(videoClips.map((clip) => clip.asset_id).filter((id): id is string => Boolean(id)))],
    [videoClips],
  );

  const transcriptQueries = useQueries({
    queries: assetIds.map((assetId) => ({
      queryKey: ["transcript", assetId],
      queryFn: async (): Promise<TranscriptOut | null> => {
        const token = getAuthToken();
        const res = await fetch(`${API_BASE}/api/assets/${assetId}/transcript`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        });
        if (res.status === 404) return null;
        if (!res.ok) throw new Error(await res.text());
        return (await res.json()) as TranscriptOut;
      },
      staleTime: 30_000,
    })),
  });

  const segmentsByAsset = React.useMemo(() => {
    const map = new Map<string, SegmentLike[]>();
    transcriptQueries.forEach((query, index) => {
      const transcript = query.data;
      if (transcript) {
        map.set(
          assetIds[index],
          (transcript.segments ?? []).map((segment) => ({
            id: segment.id,
            start_time: segment.start_time,
            end_time: segment.end_time,
            text: segment.text,
            speaker: segment.speaker,
            tokens: (segment.tokens ?? []).map((token) => ({
              start_time: token.start_time,
              end_time: token.end_time,
              text: token.text,
            })),
          })),
        );
      }
    });
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetIds, ...transcriptQueries.map((query) => query.data)]);

  const projected = React.useMemo(
    () => projectTranscript(videoClips, segmentsByAsset),
    [videoClips, segmentsByAsset],
  );
  const silences = React.useMemo(
    () => (showSilences ? detectSilences(videoClips, segmentsByAsset) : []),
    [showSilences, videoClips, segmentsByAsset],
  );
  const fillerCount = React.useMemo(
    () => projected.reduce((count, item) => count + item.tokens.filter((tok) => isFillerToken(tok.text)).length, 0),
    [projected],
  );

  // Selection keys go stale whenever the sequence changes underneath us.
  React.useEffect(() => setSelected(new Map()), [sequence.revision]);

  // ASR: kick a transcribe job for the first video clip's asset, poll it,
  // then refetch transcripts so word tokens appear.
  const startAsr = useMutation({
    mutationFn: (assetId: string) => transcribeAsset(assetId),
    onSuccess: (job) => {
      setAsrError(null);
      setAsrJobId(job.id);
    },
    onError: (error) => setAsrError(String((error as Error).message)),
  });
  const asrJob = useQuery({
    queryKey: ["job", asrJobId],
    enabled: Boolean(asrJobId),
    queryFn: () => fetchJob(asrJobId!),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "succeeded" || status === "failed" ? false : 1500;
    },
    refetchOnWindowFocus: true,
  });
  React.useEffect(() => {
    if (asrJob.data?.status === "succeeded") {
      setAsrJobId(null);
      void qc.invalidateQueries({ queryKey: ["transcript"] });
    } else if (asrJob.data?.status === "failed") {
      setAsrJobId(null);
      setAsrError(asrJob.data.error ?? t("transcribeFailed"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asrJob.data?.status]);
  const asrRunning = startAsr.isPending || Boolean(asrJobId);
  const firstAssetId = assetIds[0] ?? null;
  const transcribeButton = firstAssetId && (
    <button
      type="button"
      className="ts-tool"
      disabled={asrRunning}
      onClick={() => startAsr.mutate(firstAssetId)}
    >
      {asrRunning ? <Loader2 size={12} className="spin" /> : <Mic size={12} />}
      {asrRunning ? (asrJob.data?.message ?? t("transcribing")) : t("aiTranscribe")}
    </button>
  );

  const toggleToken = (key: string, clipId: string, srcStart: number, srcEnd: number) => {
    setSelected((current) => {
      const next = new Map(current);
      if (next.has(key)) next.delete(key);
      else next.set(key, { clipId, srcStart, srcEnd });
      return next;
    });
  };

  const groupCuts = (entries: Array<{ clipId: string; srcStart: number; srcEnd: number }>) => {
    const byClip = new Map<string, CutRange[]>();
    for (const entry of entries) {
      const ranges = byClip.get(entry.clipId) ?? [];
      ranges.push({ srcStart: entry.srcStart, srcEnd: entry.srcEnd });
      byClip.set(entry.clipId, ranges);
    }
    return [...byClip.entries()].map(([clipId, ranges]) => ({ clipId, ranges }));
  };

  const applySelected = () => {
    if (!onCutRanges || selected.size === 0) return;
    onCutRanges(groupCuts([...selected.values()]));
    setSelected(new Map());
  };

  const selectAllFillers = () => {
    setSelected((current) => {
      const next = new Map(current);
      projected.forEach((item) => {
        item.tokens.forEach((token, index) => {
          if (!isFillerToken(token.text)) return;
          next.set(`${item.clipId}:${item.segmentId}:${index}`, {
            clipId: item.clipId,
            srcStart: token.start_time,
            srcEnd: token.end_time,
          });
        });
      });
      return next;
    });
  };

  const selectAllSilences = () => {
    setSelected((current) => {
      const next = new Map(current);
      for (const gap of silences) {
        next.set(`${gap.clipId}:sil:${gap.srcStart}`, {
          clipId: gap.clipId,
          srcStart: gap.srcStart,
          srcEnd: gap.srcEnd,
        });
      }
      return next;
    });
  };

  // 文档视图:句子与静音间隙按时间线顺序交织成一篇连续文本。
  const docItems = React.useMemo(() => {
    const items: Array<
      | { kind: "sentence"; sentence: (typeof projected)[number] }
      | { kind: "silence"; gap: (typeof silences)[number] }
    > = projected.map((sentence) => ({ kind: "sentence" as const, sentence }));
    if (showSilences) {
      for (const gap of silences) items.push({ kind: "silence", gap });
    }
    return items.sort((a, b) => {
      const ta = a.kind === "sentence" ? a.sentence.timelineStart : a.gap.timelineStart;
      const tb = b.kind === "sentence" ? b.sentence.timelineStart : b.gap.timelineStart;
      return ta - tb;
    });
  }, [projected, silences, showSilences]);

  // 卡拉OK定位:播放头映射回当前片段的源时间,命中的词高亮。
  const clipById = React.useMemo(() => new Map(videoClips.map((clip) => [clip.id, clip])), [videoClips]);
  const activeSrc = React.useMemo(() => {
    for (const clip of videoClips) {
      const end = clip.timeline_start + (clip.src_out - clip.src_in) / (clip.speed || 1);
      if (playhead >= clip.timeline_start && playhead < end) {
        return { clipId: clip.id, src: clip.src_in + (playhead - clip.timeline_start) * (clip.speed || 1) };
      }
    }
    return null;
  }, [videoClips, playhead]);

  const activeSentenceRef = React.useRef<HTMLDivElement | null>(null);
  const activeSentenceKey = React.useMemo(() => {
    const hit = projected.find((item) => playhead >= item.timelineStart && playhead < item.timelineEnd);
    return hit ? `${hit.clipId}:${hit.segmentId}` : null;
  }, [projected, playhead]);
  React.useEffect(() => {
    activeSentenceRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeSentenceKey]);

  const selectedSeconds = React.useMemo(() => {
    let total = 0;
    for (const entry of selected.values()) {
      const speed = clipById.get(entry.clipId)?.speed || 1;
      total += (entry.srcEnd - entry.srcStart) / speed;
    }
    return total;
  }, [selected, clipById]);

  // 文档序的扁平词表:拖选按它计算范围,单击按它定位播放头。
  const docTokens = React.useMemo(() => {
    const list: Array<{ key: string; clipId: string; srcStart: number; srcEnd: number; timelineAt: number }> = [];
    for (const item of docItems) {
      if (item.kind !== "sentence") continue;
      const sentence = item.sentence;
      const clip = clipById.get(sentence.clipId);
      const speed = clip?.speed || 1;
      sentence.tokens.forEach((token, index) => {
        list.push({
          key: `${sentence.clipId}:${sentence.segmentId}:${index}`,
          clipId: sentence.clipId,
          srcStart: token.start_time,
          srcEnd: token.end_time,
          timelineAt: clip ? clip.timeline_start + (token.start_time - clip.src_in) / speed : sentence.timelineStart,
        });
      });
    }
    return list;
  }, [docItems, clipById]);
  const flatIndexByKey = React.useMemo(
    () => new Map(docTokens.map((token, index) => [token.key, index])),
    [docTokens],
  );
  const docTokensRef = React.useRef(docTokens);
  docTokensRef.current = docTokens;

  // 交互模型(Descript/剪映):单击 = 定位播放头;按住拖过多个词 = 标记
  // 范围(在既有选择上追加);双击 = 单词标记/取消。
  const dragRef = React.useRef<{ anchor: number; base: TokenSelection; moved: boolean } | null>(null);
  const beginWordDrag = (flatIndex: number) => {
    dragRef.current = { anchor: flatIndex, base: new Map(selected), moved: false };
  };
  const dragOverWord = (flatIndex: number) => {
    const drag = dragRef.current;
    if (!drag || (flatIndex === drag.anchor && !drag.moved)) return;
    drag.moved = true;
    const [from, to] = [Math.min(drag.anchor, flatIndex), Math.max(drag.anchor, flatIndex)];
    const next = new Map(drag.base);
    for (let index = from; index <= to; index += 1) {
      const token = docTokensRef.current[index];
      next.set(token.key, { clipId: token.clipId, srcStart: token.srcStart, srcEnd: token.srcEnd });
    }
    setSelected(next);
  };
  React.useEffect(() => {
    const onUp = () => {
      const drag = dragRef.current;
      dragRef.current = null;
      if (drag && !drag.moved) {
        const token = docTokensRef.current[drag.anchor];
        if (token) useEditorStore.getState().setPlayhead(token.timelineAt);
      }
    };
    window.addEventListener("pointerup", onUp);
    return () => window.removeEventListener("pointerup", onUp);
  }, []);

  // 按句切分:每个片段在其句子起点处切开,每句(含其后停顿)成为独立片段。
  const splitBySentence = () => {
    if (!onSplitPoints) return;
    const byClip = new Map<string, number[]>();
    for (const sentence of projected) {
      const list = byClip.get(sentence.clipId) ?? [];
      list.push(sentence.srcStart);
      byClip.set(sentence.clipId, list);
    }
    const cuts = [...byClip.entries()].map(([clipId, srcTimes]) => ({ clipId, srcTimes }));
    if (cuts.length) onSplitPoints(cuts);
  };
  // 单句独立成片段:在句首、句尾各切一刀,把该句从原片段切出来。
  const splitSentenceOut = (clipId: string, srcStart: number, srcEnd: number) => {
    onSplitPoints?.([{ clipId, srcTimes: [srcStart, srcEnd] }]);
  };
  // 在播放头当前词处切一刀(单点)。
  const splitAtPlayhead = () => {
    if (onSplitPoints && activeSrc) onSplitPoints([{ clipId: activeSrc.clipId, srcTimes: [activeSrc.src] }]);
  };

  if (projected.length === 0) {
    return (
      <div className="ts-empty">
        <MessageSquareText size={18} />
        <p>{t("transcriptEmpty")}</p>
        <p className="ts-flow-hint">{t("transcriptFlowHint")}</p>
        {transcribeButton}
        {asrError && <p className="ts-asr-error">{asrError}</p>}
      </div>
    );
  }

  return (
    <div className="ts-wrap">
      <div className="ts-tools">
        {transcribeButton}
        <button
          type="button"
          className={showSilences ? "ts-tool on" : "ts-tool"}
          title={t("silencesHint")}
          onClick={() => setShowSilences((value) => !value)}
        >
          <AudioLines size={12} /> {t("silences")}
          {showSilences && silences.length > 0 && <em>{silences.length}</em>}
        </button>
        <button type="button" className="ts-tool" title={t("fillersHint")} onClick={selectAllFillers} disabled={fillerCount === 0}>
          <Sparkles size={12} /> {t("fillers")}
          {fillerCount > 0 && <em>{fillerCount}</em>}
        </button>
        {onSplitPoints && (
          <>
            <button type="button" className="ts-tool" title={t("splitBySentenceHint")} onClick={splitBySentence}>
              <Split size={12} /> {t("splitBySentence")}
            </button>
            <button
              type="button"
              className="ts-tool"
              title={t("splitAtWordHint")}
              onClick={splitAtPlayhead}
              disabled={!activeSrc}
            >
              <Scissors size={12} /> {t("splitAtWord")}
            </button>
          </>
        )}
        {showSilences && silences.length > 0 && (
          <button type="button" className="ts-tool" title={t("removeAllSilences")} onClick={selectAllSilences}>
            {t("selectAllSilences")}
          </button>
        )}
        <span className="ts-stats">
          {t("transcriptStats")
            .replace("{n}", String(projected.length))
            .replace("{c}", String(projected.reduce((sum, item) => sum + item.text.length, 0)))}
        </span>
      </div>

      <p className="tsd-usage">{t("transcriptUsage")}</p>
      <div
        className="tsd-doc"
        onPointerOver={(event) => {
          if (!(event.buttons & 1) || !dragRef.current) return;
          const el = (event.target as HTMLElement).closest("[data-flat]");
          if (el) dragOverWord(Number(el.getAttribute("data-flat")));
        }}
      >
        {docItems.map((item) => {
          if (item.kind === "silence") {
            const gap = item.gap;
            const gapKey = `${gap.clipId}:sil:${gap.srcStart}`;
            return (
              <button
                key={gapKey}
                type="button"
                className={selected.has(gapKey) ? "tsd-gap cut" : "tsd-gap"}
                title={t("silenceGapHint")}
                onClick={() => toggleToken(gapKey, gap.clipId, gap.srcStart, gap.srcEnd)}
              >
                <AudioLines size={10} /> {gap.duration.toFixed(1)}s
              </button>
            );
          }
          const sentence = item.sentence;
          const key = `${sentence.clipId}:${sentence.segmentId}`;
          const active = key === activeSentenceKey;
          return (
            <div
              key={key}
              ref={active ? activeSentenceRef : undefined}
              className={active ? "tsd-sentence active" : "tsd-sentence"}
            >
              <div className="tsd-gutter">
                <button
                  type="button"
                  className="tsd-time timecode"
                  title={t("seekToSentence")}
                  onClick={() => useEditorStore.getState().setPlayhead(sentence.timelineStart)}
                >
                  {formatTimecode(sentence.timelineStart)}
                </button>
              </div>
              {onSplitPoints && (
                <button
                  type="button"
                  className="tsd-split"
                  title={t("splitSentenceOutHint")}
                  aria-label={t("splitSentenceOut")}
                  onClick={() => splitSentenceOut(sentence.clipId, sentence.srcStart, sentence.srcEnd)}
                >
                  <SplitSquareVertical size={11} />
                </button>
              )}
              <button
                type="button"
                className="tsd-drop"
                title={t("cutSentenceHint")}
                aria-label={t("cutSentence")}
                onClick={() => onCutSegment(sentence.clipId, sentence.srcStart, sentence.srcEnd)}
              >
                <X size={11} />
              </button>
              <p className="tsd-text">
                {sentence.speaker && (
                  <em
                    className="tsd-speaker"
                    style={{
                      background: `oklch(0.94 0.05 ${speakerHue(sentence.speaker)})`,
                      color: `oklch(0.45 0.12 ${speakerHue(sentence.speaker)})`,
                    }}
                  >
                    {sentence.speaker.replace("SPEAKER_", "说话人 ")}
                  </em>
                )}
                {sentence.tokens.length > 0
                  ? sentence.tokens.map((token, index) => {
                      const tokenKey = `${sentence.clipId}:${sentence.segmentId}:${index}`;
                      const flatIndex = flatIndexByKey.get(tokenKey) ?? -1;
                      const current =
                        activeSrc?.clipId === sentence.clipId &&
                        activeSrc.src >= token.start_time &&
                        activeSrc.src < token.end_time;
                      const classes = [
                        "tsd-word",
                        selected.has(tokenKey) ? "cut" : "",
                        isFillerToken(token.text) ? "filler" : "",
                        current ? "current" : "",
                      ]
                        .filter(Boolean)
                        .join(" ");
                      return (
                        <button
                          key={tokenKey}
                          type="button"
                          className={classes}
                          data-flat={flatIndex}
                          onPointerDown={(event) => {
                            if (event.button === 0) beginWordDrag(flatIndex);
                          }}
                          onDoubleClick={() => toggleToken(tokenKey, sentence.clipId, token.start_time, token.end_time)}
                        >
                          {token.text}
                        </button>
                      );
                    })
                  : (
                      <button
                        type="button"
                        className={selected.has(`${key}:all`) ? "tsd-word block cut" : "tsd-word block"}
                        title={t("markSentenceHint")}
                        onClick={() => useEditorStore.getState().setPlayhead(sentence.timelineStart)}
                        onDoubleClick={() => toggleToken(`${key}:all`, sentence.clipId, sentence.srcStart, sentence.srcEnd)}
                      >
                        {sentence.text}
                      </button>
                    )}
              </p>
            </div>
          );
        })}
      </div>

      {onTranslateToSubtitles && (
        <div className="ts-footer">
          <Popover open={translateOpen} onOpenChange={setTranslateOpen}>
            <PopoverTrigger asChild>
              <button type="button" className="ts-tool" disabled={translating}>
                {translating ? <Loader2 size={12} className="spin" /> : <Languages size={12} />}
                {t("transcriptTranslateToSubtitles")}
              </button>
            </PopoverTrigger>
            <PopoverContent className="sub-translate-pop" align="start">
              <strong>{t("transcriptTranslateToSubtitles")}</strong>
              <label className="sub-translate-row">
                <span>{t("subtitleTranslateTo")}</span>
                <Select value={lang} onValueChange={setLang}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TRANSLATE_LANGS.map((code) => (
                      <SelectItem key={code} value={code}>
                        {t(("lang_" + code.replace("-", "_")) as never)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              <Button
                size="sm"
                disabled={translating}
                onClick={() => {
                  setTranslateOpen(false);
                  onTranslateToSubtitles(lang);
                }}
              >
                <Languages size={13} /> {t("transcriptTranslateGo")}
              </Button>
              <small className="sub-translate-note">{t("transcriptTranslateNote")}</small>
            </PopoverContent>
          </Popover>
        </div>
      )}

      {selected.size > 0 && (
        <div className="tsd-bar">
          <span className="tsd-bar-info">
            {t("selectedWordsInfo").replace("{n}", String(selected.size)).replace("{s}", selectedSeconds.toFixed(1))}
          </span>
          <button type="button" className="ts-tool" onClick={() => setSelected(new Map())}>
            {t("clearSelection")}
          </button>
          <button type="button" className="ts-tool danger" onClick={applySelected}>
            <Trash2 size={12} /> {t("removeSelectedWords")}
          </button>
        </div>
      )}
    </div>
  );
}
