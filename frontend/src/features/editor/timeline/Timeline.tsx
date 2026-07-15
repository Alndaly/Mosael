import React from "react";
import { useQueries } from "@tanstack/react-query";
import { AudioLines, Film, Magnet, Minus, Plus, X } from "lucide-react";

import { fetchWaveform, type Asset, type Sequence, type Track, type WaveformData } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  formatRulerLabel,
  formatTimecode,
  pxToTime,
  resolveMove,
  resolveTrim,
  rulerTicks,
  sequenceDuration,
  snapCandidates,
  snapTime,
  timeToPx,
} from "@/domain/timeline/geometry";
import { downsamplePeaks, slicePeaks } from "@/domain/timeline/waveform";
import { useEditorStore } from "@/stores/editorStore";
import { TimelineClip } from "./TimelineClip";

const TRACK_HEIGHT = 48;
const RULER_HEIGHT = 26;

export interface TrimPayload {
  timeline_start: number;
  src_in: number;
  src_out: number;
}

export function Timeline({
  sequence,
  assets,
  onInsertClip,
  onMoveClip,
  onTrimClip,
  onAddTrack,
  onRemoveTrack,
  toolbarExtra,
}: {
  sequence: Sequence;
  assets: Asset[];
  onInsertClip: (args: { trackId: string; assetId: string; timelineStart: number; srcIn: number; srcOut: number }) => void;
  onMoveClip: (clipId: string, timelineStart: number) => void;
  onTrimClip: (clipId: string, payload: TrimPayload) => void;
  onAddTrack?: (kind: "video" | "audio") => void;
  onRemoveTrack?: (trackId: string) => void;
  toolbarExtra?: React.ReactNode;
}) {
  const t = useI18n();
  const playhead = useEditorStore((state) => state.playhead);
  const pxPerSecond = useEditorStore((state) => state.pxPerSecond);
  const dragDraft = useEditorStore((state) => state.dragDraft);
  const selectedClipId = useEditorStore((state) => state.selectedClipId);
  const { setPlayhead, zoomBy, selectClip, setDragDraft, setPxPerSecond } = useEditorStore.getState();
  const [snapEnabled, setSnapEnabled] = React.useState(true);
  const canvasRef = React.useRef<HTMLDivElement | null>(null);

  const tracks = sequence.tracks ?? [];
  const allClips = React.useMemo(() => tracks.flatMap((track) => track.clips ?? []), [tracks]);
  const assetById = React.useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);

  // Waveforms for audio-track clips whose assets have a cached waveform.
  const waveformAssetIds = React.useMemo(() => {
    const ids = new Set<string>();
    for (const track of tracks) {
      if (track.kind !== "audio") continue;
      for (const clip of track.clips ?? []) {
        if (assetById.get(clip.asset_id)?.media_info.has_waveform) ids.add(clip.asset_id);
      }
    }
    return [...ids];
  }, [tracks, assetById]);
  const waveformQueries = useQueries({
    queries: waveformAssetIds.map((assetId) => ({
      queryKey: ["waveform", assetId],
      queryFn: () => fetchWaveform(assetId),
      staleTime: Infinity,
    })),
  });
  const waveformByAsset = React.useMemo(() => {
    const map = new Map<string, WaveformData>();
    waveformQueries.forEach((query, index) => {
      if (query.data) map.set(waveformAssetIds[index], query.data);
    });
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [waveformAssetIds, ...waveformQueries.map((query) => query.data)]);

  const duration = Math.max(sequenceDuration(allClips), playhead) + 10;
  const contentWidth = timeToPx(duration, pxPerSecond) + 120;
  const ticks = rulerTicks(0, duration, pxPerSecond);

  const timeAtPointer = (event: { clientX: number }): number => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return 0;
    return Math.max(0, pxToTime(event.clientX - rect.left, pxPerSecond));
  };

  const capturePointer = (element: Element, pointerId: number) => {
    try {
      element.setPointerCapture(pointerId);
    } catch {
      // Synthetic events and stale pointer ids can't be captured; drag still works.
    }
  };

  const handleRulerPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    capturePointer(event.currentTarget, event.pointerId);
    setPlayhead(timeAtPointer(event));
  };

  const handleRulerPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.buttons & 1) setPlayhead(timeAtPointer(event));
  };

  const startClipDrag = (event: React.PointerEvent, track: Track, clipId: string) => {
    const clip = (track.clips ?? []).find((item) => item.id === clipId);
    if (!clip || track.locked) return;
    selectClip(clip.id);
    const startX = event.clientX;
    const origin = { ...clip };
    const candidates = snapEnabled ? snapCandidates(allClips, clip.id, playhead) : [];
    const target = event.currentTarget as HTMLElement;
    capturePointer(target, event.pointerId);

    const onMove = (moveEvent: PointerEvent) => {
      const rawStart = origin.timeline_start + pxToTime(moveEvent.clientX - startX, pxPerSecond);
      const resolved = resolveMove(origin, rawStart, candidates, pxPerSecond);
      useEditorStore.getState().setDragDraft({
        clipId: clip.id,
        trackId: track.id,
        timeline_start: resolved,
        src_in: origin.src_in,
        src_out: origin.src_out,
        kind: "move",
      });
    };
    const onUp = () => {
      target.removeEventListener("pointermove", onMove);
      target.removeEventListener("pointerup", onUp);
      const draft = useEditorStore.getState().dragDraft;
      if (draft && draft.clipId === clip.id && draft.timeline_start !== origin.timeline_start) {
        onMoveClip(clip.id, draft.timeline_start);
      } else {
        useEditorStore.getState().setDragDraft(null);
      }
    };
    target.addEventListener("pointermove", onMove);
    target.addEventListener("pointerup", onUp);
  };

  const startClipTrim = (event: React.PointerEvent, track: Track, clipId: string, edge: "start" | "end") => {
    const clip = (track.clips ?? []).find((item) => item.id === clipId);
    if (!clip || track.locked) return;
    event.stopPropagation();
    selectClip(clip.id);
    const origin = { ...clip };
    const asset = assetById.get(clip.asset_id);
    const assetDuration = typeof asset?.media_info.duration === "number" ? asset.media_info.duration : null;
    const candidates = snapEnabled ? snapCandidates(allClips, clip.id, playhead) : [];
    const target = event.currentTarget as HTMLElement;
    capturePointer(target, event.pointerId);

    const onMove = (moveEvent: PointerEvent) => {
      let rawTime = timeAtPointer(moveEvent);
      if (candidates.length > 0) rawTime = snapTime(rawTime, candidates, pxPerSecond).time;
      const result = resolveTrim(origin, edge, rawTime, assetDuration);
      useEditorStore.getState().setDragDraft({
        clipId: clip.id,
        trackId: track.id,
        ...result,
        kind: edge === "start" ? "trim-start" : "trim-end",
      });
    };
    const onUp = () => {
      target.removeEventListener("pointermove", onMove);
      target.removeEventListener("pointerup", onUp);
      const draft = useEditorStore.getState().dragDraft;
      if (draft && draft.clipId === clip.id) {
        onTrimClip(clip.id, { timeline_start: draft.timeline_start, src_in: draft.src_in, src_out: draft.src_out });
      }
    };
    target.addEventListener("pointermove", onMove);
    target.addEventListener("pointerup", onUp);
  };

  const handleDrop = (event: React.DragEvent, track: Track) => {
    event.preventDefault();
    const assetId = event.dataTransfer.getData("application/x-mibu-asset");
    const asset = assetById.get(assetId);
    if (!asset || !trackAcceptsAsset(track, asset)) return;
    const assetDuration = typeof asset.media_info.duration === "number" ? asset.media_info.duration : 5;
    let start = timeAtPointer(event);
    if (snapEnabled) start = snapTime(start, snapCandidates(allClips, null, playhead), pxPerSecond).time;
    onInsertClip({
      trackId: track.id,
      assetId: asset.id,
      timelineStart: start,
      srcIn: 0,
      srcOut: assetDuration,
    });
  };

  const handleWheel = (event: React.WheelEvent) => {
    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      zoomBy(event.deltaY < 0 ? 1.15 : 1 / 1.15);
    }
  };

  return (
    <div className="tl" onWheel={handleWheel}>
      <div className="tl-toolbar">
        <span className="timecode tl-readout">{formatTimecode(playhead)}</span>
        <div className="tl-toolbar-actions">
          {toolbarExtra}
          {onAddTrack && (
            <>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon-sm" onClick={() => onAddTrack("video")} aria-label={t("addVideoTrack")}>
                    <Film size={14} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("addVideoTrack")}</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon-sm" onClick={() => onAddTrack("audio")} aria-label={t("addAudioTrack")}>
                    <AudioLines size={14} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("addAudioTrack")}</TooltipContent>
              </Tooltip>
            </>
          )}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={snapEnabled ? "secondary" : "ghost"}
                size="icon-sm"
                onClick={() => setSnapEnabled((value) => !value)}
                aria-pressed={snapEnabled}
                aria-label="Snap"
              >
                <Magnet size={14} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Snap</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" onClick={() => zoomBy(1 / 1.3)} aria-label={t("zoomOut")}>
                <Minus size={14} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("zoomOut")}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" onClick={() => zoomBy(1.3)} aria-label={t("zoomIn")}>
                <Plus size={14} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("zoomIn")}</TooltipContent>
          </Tooltip>
        </div>
      </div>
      <div className="tl-body">
        <div className="tl-labels">
          <div className="tl-labels-spacer" style={{ height: RULER_HEIGHT }} />
          {tracks.map((track) => (
            <div className="tl-label" key={track.id} style={{ height: TRACK_HEIGHT }}>
              <span className={`tl-label-dot dot-${track.kind}`} />
              {track.name}
              {onRemoveTrack && (track.clips ?? []).length === 0 && (
                <button
                  type="button"
                  className="tl-label-remove"
                  aria-label={t("removeTrack")}
                  onClick={() => onRemoveTrack(track.id)}
                >
                  <X size={11} />
                </button>
              )}
            </div>
          ))}
        </div>
        <div className="tl-hscroll">
          <div className="tl-canvas" ref={canvasRef} style={{ width: contentWidth }}>
            <div
              className="tl-ruler"
              style={{ height: RULER_HEIGHT }}
              onPointerDown={handleRulerPointerDown}
              onPointerMove={handleRulerPointerMove}
            >
              {ticks.map((tick) => (
                <div
                  key={tick.time}
                  className={tick.major ? "tl-tick major" : "tl-tick"}
                  style={{ left: timeToPx(tick.time, pxPerSecond) }}
                >
                  {tick.major && <span className="timecode">{formatRulerLabel(tick.time)}</span>}
                </div>
              ))}
            </div>
            {tracks.map((track) => (
              <div
                className="tl-lane"
                key={track.id}
                style={{ height: TRACK_HEIGHT }}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => handleDrop(event, track)}
                onPointerDown={(event) => {
                  if (event.target === event.currentTarget) selectClip(null);
                }}
              >
                {(track.clips ?? []).map((clip) => {
                  const draft = dragDraft && dragDraft.clipId === clip.id ? dragDraft : null;
                  const display = draft ?? clip;
                  const waveform = track.kind === "audio" ? waveformByAsset.get(clip.asset_id) : undefined;
                  const clipWidth = Math.max(10, timeToPx(display.src_out - display.src_in, pxPerSecond));
                  const peaks = waveform
                    ? downsamplePeaks(
                        slicePeaks(waveform.peaks, waveform.duration, display.src_in, display.src_out),
                        Math.max(24, Math.floor(clipWidth / 3)),
                      )
                    : undefined;
                  return (
                    <TimelineClip
                      key={clip.id}
                      trackKind={track.kind}
                      name={assetById.get(clip.asset_id)?.name ?? clip.asset_id.slice(0, 8)}
                      left={timeToPx(display.timeline_start, pxPerSecond)}
                      width={clipWidth}
                      selected={selectedClipId === clip.id}
                      dragging={Boolean(draft)}
                      peaks={peaks}
                      onPointerDown={(event) => startClipDrag(event, track, clip.id)}
                      onTrimPointerDown={(event, edge) => startClipTrim(event, track, clip.id, edge)}
                      onSelect={() => selectClip(clip.id)}
                    />
                  );
                })}
              </div>
            ))}
            <div className="tl-playhead" style={{ left: timeToPx(playhead, pxPerSecond) }}>
              <div className="tl-playhead-cap" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function trackAcceptsAsset(track: Track, asset: Asset): boolean {
  if (track.kind === "video") return asset.kind === "video" || asset.kind === "image";
  if (track.kind === "audio") return asset.kind === "audio";
  return false;
}
