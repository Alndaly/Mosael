import React from "react";
import { useQueries } from "@tanstack/react-query";
import { AudioLines, MessageSquareText, Sparkles, Trash2, X } from "lucide-react";

import { API_BASE, getAuthToken, type Sequence } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { formatTimecode } from "@/domain/timeline/geometry";
import {
  detectSilences,
  isFillerToken,
  projectTranscript,
  type SegmentLike,
} from "@/domain/timeline/transcriptProjection";
import { useEditorStore } from "@/stores/editorStore";

type TranscriptOut = components["schemas"]["TranscriptOut"];

export interface CutRange {
  srcStart: number;
  srcEnd: number;
}

/** Selected word key → its cut payload. */
type TokenSelection = Map<string, { clipId: string; srcStart: number; srcEnd: number }>;

export function TranscriptPanel({
  sequence,
  onCutSegment,
  onCutRanges,
}: {
  sequence: Sequence;
  onCutSegment: (clipId: string, srcStart: number, srcEnd: number) => void;
  onCutRanges?: (cuts: Array<{ clipId: string; ranges: CutRange[] }>) => void;
}) {
  const t = useI18n();
  const playhead = useEditorStore((state) => state.playhead);
  const [expandedId, setExpandedId] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<TokenSelection>(new Map());
  const [showSilences, setShowSilences] = React.useState(false);

  const videoClips = React.useMemo(() => {
    const track = (sequence.tracks ?? []).find((item) => item.kind === "video");
    return track?.clips ?? [];
  }, [sequence]);
  const assetIds = React.useMemo(() => [...new Set(videoClips.map((clip) => clip.asset_id))], [videoClips]);

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

  const removeAllSilences = () => {
    if (!onCutRanges || silences.length === 0) return;
    onCutRanges(
      groupCuts(silences.map((gap) => ({ clipId: gap.clipId, srcStart: gap.srcStart, srcEnd: gap.srcEnd }))),
    );
  };

  if (projected.length === 0) {
    return (
      <div className="ts-empty">
        <MessageSquareText size={18} />
        <p>{t("transcriptEmpty")}</p>
      </div>
    );
  }

  return (
    <div className="ts-wrap">
      <div className="ts-tools">
        <button
          type="button"
          className={showSilences ? "ts-tool on" : "ts-tool"}
          onClick={() => setShowSilences((value) => !value)}
        >
          <AudioLines size={12} /> {t("silences")}
          {showSilences && silences.length > 0 && <em>{silences.length}</em>}
        </button>
        <button type="button" className="ts-tool" onClick={selectAllFillers} disabled={fillerCount === 0}>
          <Sparkles size={12} /> {t("fillers")}
          {fillerCount > 0 && <em>{fillerCount}</em>}
        </button>
        {selected.size > 0 && (
          <button type="button" className="ts-tool danger" onClick={applySelected}>
            <Trash2 size={12} /> {t("removeSelectedWords")} ({selected.size})
          </button>
        )}
      </div>
      {showSilences && silences.length > 0 && (
        <div className="ts-silences">
          {silences.map((gap) => (
            <div key={`${gap.clipId}:${gap.srcStart}`} className="ts-item ts-silence">
              <button
                type="button"
                className="ts-seek"
                onClick={() => useEditorStore.getState().setPlayhead(gap.timelineStart)}
              >
                <span className="ts-time timecode">{formatTimecode(gap.timelineStart)}</span>
                <span className="ts-text">
                  {t("silenceGap")} · {gap.duration.toFixed(1)}s
                </span>
              </button>
              <button
                type="button"
                className="ts-cut"
                title={t("removeSilence")}
                aria-label={t("removeSilence")}
                onClick={() => onCutRanges?.([{ clipId: gap.clipId, ranges: [{ srcStart: gap.srcStart, srcEnd: gap.srcEnd }] }])}
              >
                <X size={12} />
              </button>
            </div>
          ))}
          <button type="button" className="ts-tool danger ts-silence-all" onClick={removeAllSilences}>
            <Trash2 size={12} /> {t("removeAllSilences")} ({silences.length})
          </button>
        </div>
      )}
      <div className="ts-list">
        {projected.map((item) => {
          const key = `${item.clipId}:${item.segmentId}`;
          const active = playhead >= item.timelineStart && playhead < item.timelineEnd;
          const expanded = expandedId === key && item.tokens.length > 0;
          return (
            <div key={key} className={active ? "ts-item active" : "ts-item"}>
              {expanded ? (
                <div className="ts-seek ts-expanded">
                  <button
                    type="button"
                    className="ts-time timecode ts-time-btn"
                    onClick={() => setExpandedId(null)}
                  >
                    {formatTimecode(item.timelineStart)}
                  </button>
                  <span className="ts-tokens">
                    {item.tokens.map((token, index) => {
                      const tokenKey = `${item.clipId}:${item.segmentId}:${index}`;
                      const classes = [
                        "ts-token",
                        selected.has(tokenKey) ? "cut" : "",
                        isFillerToken(token.text) ? "filler" : "",
                      ]
                        .filter(Boolean)
                        .join(" ");
                      return (
                        <button
                          key={tokenKey}
                          type="button"
                          className={classes}
                          onClick={() => toggleToken(tokenKey, item.clipId, token.start_time, token.end_time)}
                        >
                          {token.text}
                        </button>
                      );
                    })}
                  </span>
                </div>
              ) : (
                <button
                  type="button"
                  className="ts-seek"
                  onClick={() => {
                    useEditorStore.getState().setPlayhead(item.timelineStart);
                    if (item.tokens.length > 0) setExpandedId(key);
                  }}
                >
                  <span className="ts-time timecode">{formatTimecode(item.timelineStart)}</span>
                  <span className="ts-text">
                    {item.speaker && <em>{item.speaker}</em>}
                    {item.text}
                    {item.clipped && <small> · {t("transcriptClipped")}</small>}
                  </span>
                </button>
              )}
              <button
                type="button"
                className="ts-cut"
                title={t("cutSentence")}
                aria-label={t("cutSentence")}
                onClick={() => onCutSegment(item.clipId, item.srcStart, item.srcEnd)}
              >
                <X size={12} />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
