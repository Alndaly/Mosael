import React from "react";
import { useQueries } from "@tanstack/react-query";
import { MessageSquareText } from "lucide-react";

import { API_BASE, type Sequence } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { formatTimecode } from "@/domain/timeline/geometry";
import { projectTranscript, type SegmentLike } from "@/domain/timeline/transcriptProjection";
import { useEditorStore } from "@/stores/editorStore";

type TranscriptOut = components["schemas"]["TranscriptOut"];

export function TranscriptPanel({ sequence }: { sequence: Sequence }) {
  const t = useI18n();
  const playhead = useEditorStore((state) => state.playhead);

  const videoClips = React.useMemo(() => {
    const track = (sequence.tracks ?? []).find((item) => item.kind === "video");
    return track?.clips ?? [];
  }, [sequence]);
  const assetIds = React.useMemo(() => [...new Set(videoClips.map((clip) => clip.asset_id))], [videoClips]);

  const transcriptQueries = useQueries({
    queries: assetIds.map((assetId) => ({
      queryKey: ["transcript", assetId],
      queryFn: async (): Promise<TranscriptOut | null> => {
        const res = await fetch(`${API_BASE}/api/assets/${assetId}/transcript`);
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

  if (projected.length === 0) {
    return (
      <div className="ts-empty">
        <MessageSquareText size={18} />
        <p>{t("transcriptEmpty")}</p>
      </div>
    );
  }

  return (
    <div className="ts-list">
      {projected.map((item) => {
        const active = playhead >= item.timelineStart && playhead < item.timelineEnd;
        return (
          <button
            type="button"
            key={`${item.clipId}:${item.segmentId}`}
            className={active ? "ts-item active" : "ts-item"}
            onClick={() => useEditorStore.getState().setPlayhead(item.timelineStart)}
          >
            <span className="ts-time timecode">{formatTimecode(item.timelineStart)}</span>
            <span className="ts-text">
              {item.speaker && <em>{item.speaker}</em>}
              {item.text}
              {item.clipped && <small> · {t("transcriptClipped")}</small>}
            </span>
          </button>
        );
      })}
    </div>
  );
}
