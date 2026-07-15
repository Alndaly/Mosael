import React from "react";
import { Plus, Trash2, Type } from "lucide-react";

import type { Sequence } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { clipEnd, formatTimecode } from "@/domain/timeline/geometry";
import { useEditorStore } from "@/stores/editorStore";

/**
 * Subtitle list editor (老版 mibu-video 的字幕可见入口): every text clip on
 * every subtitle track, in timeline order — click the timecode to seek, edit
 * the text inline, delete, or add a new one at the playhead.
 */
export function SubtitlePanel({
  sequence,
  onSetText,
  onAddSubtitle,
  onDeleteClip,
}: {
  sequence: Sequence;
  onSetText: (clipId: string, text: string) => void;
  onAddSubtitle: () => void;
  onDeleteClip: (clipId: string) => void;
}) {
  const t = useI18n();
  const playhead = useEditorStore((state) => state.playhead);
  const selectClip = useEditorStore((state) => state.selectClip);

  const subtitles = React.useMemo(
    () =>
      (sequence.tracks ?? [])
        .filter((track) => track.kind === "subtitle")
        .flatMap((track) => track.clips ?? [])
        .sort((a, b) => a.timeline_start - b.timeline_start),
    [sequence],
  );

  return (
    <div className="sub-panel">
      <div className="sub-list">
        {subtitles.length === 0 && (
          <div className="empty-inline">
            <Type size={16} />
            {t("subtitleEmptyBody")}
          </div>
        )}
        {subtitles.map((clip) => {
          const active = playhead >= clip.timeline_start && playhead < clipEnd(clip);
          return (
            <div key={clip.id} className={active ? "sub-item active" : "sub-item"}>
              <div className="sub-item-head">
                <button
                  type="button"
                  className="ts-time timecode ts-time-btn"
                  title={t("seekToSubtitle")}
                  onClick={() => {
                    useEditorStore.getState().setPlayhead(clip.timeline_start);
                    selectClip(clip.id);
                  }}
                >
                  {formatTimecode(clip.timeline_start)} – {formatTimecode(clipEnd(clip))}
                </button>
                <button
                  type="button"
                  className="sub-delete"
                  title={t("deleteClip")}
                  aria-label={t("deleteClip")}
                  onClick={() => onDeleteClip(clip.id)}
                >
                  <Trash2 size={12} />
                </button>
              </div>
              <textarea
                key={`sub-${clip.id}-${clip.text_override}`}
                className="subtitle-input"
                rows={2}
                defaultValue={clip.text_override ?? ""}
                onBlur={(event) => {
                  const value = event.target.value.trim();
                  if (value && value !== clip.text_override) onSetText(clip.id, value);
                }}
              />
            </div>
          );
        })}
      </div>
      <div className="sub-footer">
        <button type="button" className="ts-tool" title={t("addSubtitleAtPlayhead")} onClick={onAddSubtitle}>
          <Plus size={12} /> {t("addSubtitleAtPlayhead")}
        </button>
      </div>
    </div>
  );
}
