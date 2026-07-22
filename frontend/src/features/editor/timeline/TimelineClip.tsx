import React from "react";
import { AudioLines, Copy, Scissors, Trash2, Waves } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { waveformPolygonPoints } from "@/domain/timeline/waveform";

export function TimelineClip({
  trackKind,
  name,
  left,
  width,
  selected,
  dragging,
  peaks,
  onPointerDown,
  onTrimPointerDown,
  onSelect,
  onDelete,
  onRippleDelete,
  onSplit,
  onDuplicate,
  onDetachAudio,
}: {
  trackKind: string;
  name: string;
  left: number;
  width: number;
  selected: boolean;
  dragging: boolean;
  peaks?: number[];
  onPointerDown: (event: React.PointerEvent) => void;
  onTrimPointerDown: (event: React.PointerEvent, edge: "start" | "end") => void;
  onSelect: () => void;
  onDelete?: () => void;
  onRippleDelete?: () => void;
  onSplit?: () => void;
  onDuplicate?: () => void;
  onDetachAudio?: () => void;
}) {
  const t = useI18n();
  const className = [
    "tl-clip",
    `tl-clip-${trackKind}`,
    selected ? "selected" : "",
    dragging ? "dragging" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const clip = (
    <div
      className={className}
      style={{ left, width }}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        onSelect();
        onPointerDown(event);
      }}
      onContextMenu={onSelect}
      role="button"
      tabIndex={-1}
      title={name}
    >
      {peaks && peaks.length > 0 && (
        <svg className="tl-clip-wave" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden>
          <polygon points={waveformPolygonPoints(peaks)} />
        </svg>
      )}
      <span
        className="tl-clip-handle left"
        onPointerDown={(event) => {
          if (event.button === 0) onTrimPointerDown(event, "start");
        }}
      />
      <span className="tl-clip-name">{name}</span>
      <span
        className="tl-clip-handle right"
        onPointerDown={(event) => {
          if (event.button === 0) onTrimPointerDown(event, "end");
        }}
      />
    </div>
  );

  if (!onDelete) return clip;
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{clip}</ContextMenuTrigger>
      <ContextMenuContent>
        {onSplit && (
          <ContextMenuItem onSelect={onSplit}>
            <Scissors /> {t("splitAtPlayhead")}
          </ContextMenuItem>
        )}
        {onDuplicate && (
          <ContextMenuItem onSelect={onDuplicate}>
            <Copy /> {t("duplicateClip")}
          </ContextMenuItem>
        )}
        {onDetachAudio && (
          <ContextMenuItem onSelect={onDetachAudio}>
            <AudioLines /> {t("detachAudio")}
          </ContextMenuItem>
        )}
        <ContextMenuSeparator />
        <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={onDelete}>
          <Trash2 /> {t("deleteClip")}
        </ContextMenuItem>
        {onRippleDelete && (
          <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={onRippleDelete}>
            <Waves /> {t("rippleDelete")}
          </ContextMenuItem>
        )}
      </ContextMenuContent>
    </ContextMenu>
  );
}
