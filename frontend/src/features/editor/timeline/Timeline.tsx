import React from "react";
import { useQueries } from "@tanstack/react-query";
import { AudioLines, BetweenHorizontalStart, CircleHelp, Copy, Film, Lock, LockOpen, Magnet, Minus, MousePointer2, Plus, Replace, Scissors, Slice, Trash2, Type, Volume2, VolumeX, Waves, X } from "lucide-react";

import { fetchWaveform, type Asset, type Sequence, type Track, type WaveformData } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  clipEnd,
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
import { MIN_PX_PER_SECOND, useEditorStore } from "@/stores/editorStore";
import { TimelineClip } from "./TimelineClip";

const TRACK_HEIGHT = 48;
const RULER_HEIGHT = 26;

// Peaks are expensive (slice + downsample over the whole waveform) and were recomputed for
// EVERY audio clip on EVERY dragDraft change — the drag felt laggy. Cache by the inputs that
// actually affect the shape; during a drag only the dragged clip's key changes, the rest hit.
function cachedPeaks(
  cache: Map<string, number[]>,
  assetId: string,
  waveform: WaveformData,
  srcIn: number,
  srcOut: number,
  clipWidth: number,
): number[] {
  const buckets = Math.max(24, Math.floor(clipWidth / 3));
  const key = `${assetId}:${srcIn.toFixed(3)}:${srcOut.toFixed(3)}:${buckets}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const value = downsamplePeaks(slicePeaks(waveform.peaks, waveform.duration, srcIn, srcOut), buckets);
  if (cache.size > 400) cache.clear();
  cache.set(key, value);
  return value;
}

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
  onMoveClipToNewLayer,
  onTrimClip,
  onAddTrack,
  onRemoveTrack,
  onDeleteClip,
  onRippleDeleteClip,
  onSplitClip,
  onSplitClipAt,
  onDuplicateClip,
  onSetTrackState,
  toolbarExtra,
}: {
  sequence: Sequence;
  assets: Asset[];
  onInsertClip: (args: { trackId: string; assetId: string; timelineStart: number; srcIn: number; srcOut: number }) => void;
  onMoveClip: (clipId: string, timelineStart: number, trackId?: string, ripple?: boolean) => void;
  onMoveClipToNewLayer?: (clipId: string, timelineStart: number) => void;
  onTrimClip: (clipId: string, payload: TrimPayload) => void;
  onAddTrack?: (kind: "video" | "audio" | "subtitle") => void;
  onRemoveTrack?: (trackId: string) => void;
  onDeleteClip?: (clipId: string) => void;
  onRippleDeleteClip?: (clipId: string) => void;
  onSplitClip?: (clipId: string) => void;
  onSplitClipAt?: (clipId: string, srcTime: number) => void;
  onDuplicateClip?: (clipId: string) => void;
  onSetTrackState?: (trackId: string, body: { muted?: boolean; locked?: boolean; solo?: boolean; duck?: boolean }) => void;
  toolbarExtra?: React.ReactNode;
}) {
  const t = useI18n();
  const playhead = useEditorStore((state) => state.playhead);
  const pxPerSecond = useEditorStore((state) => state.pxPerSecond);
  const dragDraft = useEditorStore((state) => state.dragDraft);
  const selectedClipIds = useEditorStore((state) => state.selectedClipIds);
  const { setPlayhead, selectClip, setDragDraft, setPxPerSecond } = useEditorStore.getState();
  const [snapEnabled, setSnapEnabled] = React.useState(true);
  const canvasRef = React.useRef<HTMLDivElement | null>(null);
  const hscrollRef = React.useRef<HTMLDivElement | null>(null);
  const labelsRef = React.useRef<HTMLDivElement | null>(null);
  const peaksCache = React.useRef<Map<string, number[]>>(new Map());
  const draggingAsset = useEditorStore((state) => state.draggingAsset);
  const tool = useEditorStore((state) => state.tool);
  const editMode = useEditorStore((state) => state.editMode);
  const [dropGhost, setDropGhost] = React.useState<{ trackId: string; start: number; duration: number } | null>(null);
  const [marquee, setMarquee] = React.useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null);
  const [helpOpen, setHelpOpen] = React.useState(false);
  // True while dragging a video clip above the top track — drop creates a new layer.
  const [newLayerDrag, setNewLayerDrag] = React.useState(false);

  const tracks = sequence.tracks ?? [];
  const allClips = React.useMemo(() => tracks.flatMap((track) => track.clips ?? []), [tracks]);

  // Insert mode: while dragging, downstream clips on the target track visibly part
  // to make room (DaVinci "段落挤开"). This is the timeline width of the dragged clip.
  const dragMoveDuration = React.useMemo(() => {
    if (!dragDraft || dragDraft.kind !== "move") return 0;
    const src = allClips.find((item) => item.id === dragDraft.clipId);
    return src ? (dragDraft.src_out - dragDraft.src_in) / (src.speed || 1) : 0;
  }, [dragDraft, allClips]);

  // Insert-mode ripple preview: downstream clips on the target track part only by
  // the actual overlap (mirrors the backend), so a nudge doesn't shove everything.
  const insertRipple = React.useMemo(() => {
    if (editMode !== "insert" || !dragDraft || dragDraft.kind !== "move") return null;
    const start = dragDraft.timeline_start;
    const end = start + dragMoveDuration;
    const downstream = (tracks.find((t) => t.id === dragDraft.trackId)?.clips ?? []).filter(
      (c) => c.id !== dragDraft.clipId && c.timeline_start >= start - 1e-9,
    );
    if (!downstream.length) return null;
    const shift = end - Math.min(...downstream.map((c) => c.timeline_start));
    return shift > 1e-9 ? { trackId: dragDraft.trackId, from: start, shift } : null;
  }, [editMode, dragDraft, dragMoveDuration, tracks]);
  const assetById = React.useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);

  // Waveforms for audio-track clips whose assets have a cached waveform.
  const waveformAssetIds = React.useMemo(() => {
    const ids = new Set<string>();
    for (const track of tracks) {
      if (track.kind !== "audio") continue;
      for (const clip of track.clips ?? []) {
        if (clip.asset_id && assetById.get(clip.asset_id)?.media_info.has_waveform) ids.add(clip.asset_id);
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

  // Zoom out can't go below "the whole timeline fits the viewport" — past that is dead space.
  const applyZoom = (factor: number) => {
    const viewport = hscrollRef.current?.clientWidth ?? 0;
    const fitPx = viewport > 0 ? Math.max(MIN_PX_PER_SECOND, (viewport - 130) / Math.max(duration, 1)) : MIN_PX_PER_SECOND;
    setPxPerSecond(Math.max(fitPx, pxPerSecond * factor));
  };
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

  const laneTrackAt = (clientY: number, sourceKind: string): Track | null => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const laneIndex = Math.floor((clientY - rect.top - RULER_HEIGHT) / TRACK_HEIGHT);
    const candidate = tracks[laneIndex];
    if (!candidate || candidate.kind !== sourceKind || candidate.locked) return null;
    return candidate;
  };

  const startMarquee = (event: React.PointerEvent) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const origin = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    let moved = false;

    const onMove = (moveEvent: PointerEvent) => {
      const x = moveEvent.clientX - rect.left;
      const y = moveEvent.clientY - rect.top;
      if (!moved && Math.abs(x - origin.x) < 4 && Math.abs(y - origin.y) < 4) return;
      moved = true;
      setMarquee({ x1: origin.x, y1: origin.y, x2: x, y2: y });
      const t1 = pxToTime(Math.min(origin.x, x), pxPerSecond);
      const t2 = pxToTime(Math.max(origin.x, x), pxPerSecond);
      const rowTop = Math.floor((Math.min(origin.y, y) - RULER_HEIGHT) / TRACK_HEIGHT);
      const rowBottom = Math.floor((Math.max(origin.y, y) - RULER_HEIGHT) / TRACK_HEIGHT);
      const hits: string[] = [];
      tracks.forEach((track, index) => {
        if (index < rowTop || index > rowBottom) return;
        for (const clip of track.clips ?? []) {
          if (clip.timeline_start < t2 && clipEnd(clip) > t1) hits.push(clip.id);
        }
      });
      useEditorStore.getState().selectClips(hits);
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      setMarquee(null);
      if (!moved) selectClip(null);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const startClipDrag = (event: React.PointerEvent, track: Track, clipId: string) => {
    const clip = (track.clips ?? []).find((item) => item.id === clipId);
    if (!clip || track.locked) return;
    if (tool === "blade") {
      // Blade (B): one click cuts the clip right where you clicked.
      if (onSplitClipAt) {
        const clickTime = timeAtPointer(event);
        const srcTime = clip.src_in + (clickTime - clip.timeline_start) * (clip.speed || 1);
        onSplitClipAt(clip.id, srcTime);
      }
      return;
    }
    if (event.shiftKey || event.metaKey || event.ctrlKey) {
      useEditorStore.getState().toggleSelectClip(clip.id);
      return;
    }
    if (!useEditorStore.getState().selectedClipIds.includes(clip.id)) selectClip(clip.id);
    const startX = event.clientX;
    const origin = { ...clip };
    const candidates = snapEnabled ? snapCandidates(allClips, clip.id, playhead) : [];

    // Listen on window, NOT the clip element: a cross-track drag hides the clip in its
    // source lane (it unmounts), which would sever element-bound listeners mid-drag and
    // freeze the drag with no pointerup. window survives the unmount. (Mirrors startMarquee.)
    let wantNewLayer = false;
    const onMove = (moveEvent: PointerEvent) => {
      const rawStart = origin.timeline_start + pxToTime(moveEvent.clientX - startX, pxPerSecond);
      const resolved = resolveMove(origin, rawStart, candidates, pxPerSecond);
      const rect = canvasRef.current?.getBoundingClientRect();
      // Dragged above the topmost lane → intent to spin up a new video layer.
      wantNewLayer = Boolean(
        rect && onMoveClipToNewLayer && track.kind === "video" && moveEvent.clientY - rect.top - RULER_HEIGHT < 0,
      );
      setNewLayerDrag(wantNewLayer);
      const lane = wantNewLayer ? null : laneTrackAt(moveEvent.clientY, track.kind);
      useEditorStore.getState().setDragDraft({
        clipId: clip.id,
        trackId: lane?.id ?? track.id,
        timeline_start: resolved,
        src_in: origin.src_in,
        src_out: origin.src_out,
        kind: "move",
      });
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      setNewLayerDrag(false);
      const draft = useEditorStore.getState().dragDraft;
      if (wantNewLayer && onMoveClipToNewLayer && draft && draft.clipId === clip.id) {
        onMoveClipToNewLayer(clip.id, draft.timeline_start);
      } else if (
        draft &&
        draft.clipId === clip.id &&
        (draft.timeline_start !== origin.timeline_start || draft.trackId !== track.id)
      ) {
        // Insert mode ripples the destination track's downstream clips aside.
        const ripple = useEditorStore.getState().editMode === "insert";
        onMoveClip(clip.id, draft.timeline_start, draft.trackId !== track.id ? draft.trackId : undefined, ripple);
      } else {
        useEditorStore.getState().setDragDraft(null);
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const startClipTrim = (event: React.PointerEvent, track: Track, clipId: string, edge: "start" | "end") => {
    const clip = (track.clips ?? []).find((item) => item.id === clipId);
    if (!clip || track.locked) return;
    event.stopPropagation();
    selectClip(clip.id);
    const origin = { ...clip };
    const asset = clip.asset_id ? assetById.get(clip.asset_id) : undefined;
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

  const handleDragOver = (event: React.DragEvent, track: Track) => {
    event.preventDefault();
    if (!draggingAsset) return;
    const accepts =
      (track.kind === "video" && (draggingAsset.kind === "video" || draggingAsset.kind === "image")) ||
      (track.kind === "audio" && draggingAsset.kind === "audio");
    if (!accepts || track.locked) {
      if (dropGhost?.trackId === track.id) setDropGhost(null);
      return;
    }
    let start = timeAtPointer(event);
    if (snapEnabled) start = snapTime(start, snapCandidates(allClips, null, playhead), pxPerSecond).time;
    setDropGhost({ trackId: track.id, start, duration: draggingAsset.duration });
  };

  const handleDrop = (event: React.DragEvent, track: Track) => {
    event.preventDefault();
    setDropGhost(null);
    const assetId = event.dataTransfer.getData("application/x-mibu-asset");
    const asset = assetById.get(assetId);
    if (!asset || !trackAcceptsAsset(track, asset) || track.locked) return;
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
      applyZoom(event.deltaY < 0 ? 1.15 : 1 / 1.15);
    }
  };

  return (
    <div className="tl" data-tool={tool} onWheel={handleWheel}>
      <div className="tl-toolbar">
        <div className="tl-toolbar-left">
          <div className="seg tl-tool-seg" role="group" aria-label={t("editTools")}>
            <button
              type="button"
              className={tool === "select" ? "seg-btn active" : "seg-btn"}
              title={t("toolSelectHint")}
              aria-pressed={tool === "select"}
              onClick={() => useEditorStore.getState().setTool("select")}
            >
              <MousePointer2 size={12} /> {t("toolSelect")}
            </button>
            <button
              type="button"
              className={tool === "blade" ? "seg-btn active" : "seg-btn"}
              title={t("toolBladeHint")}
              aria-pressed={tool === "blade"}
              onClick={() => useEditorStore.getState().setTool("blade")}
            >
              <Slice size={12} /> {t("toolBlade")}
            </button>
          </div>
          <div className="seg tl-tool-seg" role="group" aria-label={t("editMode")}>
            <button
              type="button"
              className={editMode === "overwrite" ? "seg-btn active" : "seg-btn"}
              title={t("editModeOverwriteHint")}
              aria-pressed={editMode === "overwrite"}
              onClick={() => useEditorStore.getState().setEditMode("overwrite")}
            >
              <Replace size={12} /> {t("editModeOverwrite")}
            </button>
            <button
              type="button"
              className={editMode === "insert" ? "seg-btn active" : "seg-btn"}
              title={t("editModeInsertHint")}
              aria-pressed={editMode === "insert"}
              onClick={() => useEditorStore.getState().setEditMode("insert")}
            >
              <BetweenHorizontalStart size={12} /> {t("editModeInsert")}
            </button>
          </div>
          <span className="timecode tl-readout">
            {formatTimecode(playhead)}
            <em> / {formatTimecode(sequenceDuration(allClips))}</em>
          </span>
          <span className="tl-clip-count">
            {t("clipCount").replace("{n}", String(allClips.length))} · {sequence.width}×{sequence.height} ·{" "}
            {Math.round(sequence.fps)}fps
          </span>
        </div>
        <div className="tl-toolbar-actions">
          {toolbarExtra}
          {(onSplitClip || onDuplicateClip || onDeleteClip) && <span className="tl-toolbar-sep" />}
          {onSplitClip && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  disabled={!selectedClipIds.length}
                  onClick={() => selectedClipIds[0] && onSplitClip(selectedClipIds[selectedClipIds.length - 1])}
                  aria-label={t("splitAtPlayhead")}
                >
                  <Scissors size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("splitAtPlayhead")}</TooltipContent>
            </Tooltip>
          )}
          {onDuplicateClip && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  disabled={!selectedClipIds.length}
                  onClick={() => selectedClipIds[0] && onDuplicateClip(selectedClipIds[selectedClipIds.length - 1])}
                  aria-label={t("duplicateClip")}
                >
                  <Copy size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("duplicateClip")}</TooltipContent>
            </Tooltip>
          )}
          {onRippleDeleteClip && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  disabled={!selectedClipIds.length}
                  onClick={() => selectedClipIds.forEach((clipId) => onRippleDeleteClip(clipId))}
                  aria-label={t("rippleDelete")}
                >
                  <Waves size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("rippleDelete")}</TooltipContent>
            </Tooltip>
          )}
          {onDeleteClip && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  disabled={!selectedClipIds.length}
                  onClick={() => selectedClipIds.forEach((clipId) => onDeleteClip(clipId))}
                  aria-label={t("deleteClip")}
                >
                  <Trash2 size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("deleteClip")}</TooltipContent>
            </Tooltip>
          )}
          <span className="tl-toolbar-sep" />
          {onAddTrack && (
            <>
              <button type="button" className="tl-add-track" title={t("addVideoTrackHint")} onClick={() => onAddTrack("video")}>
                <Plus size={11} />
                <Film size={12} /> {t("trackVideoShort")}
              </button>
              <button type="button" className="tl-add-track" title={t("addAudioTrackHint")} onClick={() => onAddTrack("audio")}>
                <Plus size={11} />
                <AudioLines size={12} /> {t("trackAudioShort")}
              </button>
              <button type="button" className="tl-add-track" title={t("addSubtitleTrackHint")} onClick={() => onAddTrack("subtitle")}>
                <Plus size={11} />
                <Type size={12} /> {t("trackSubtitleShort")}
              </button>
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
              <Button variant="ghost" size="icon-sm" onClick={() => applyZoom(1 / 1.3)} aria-label={t("zoomOut")}>
                <Minus size={14} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("zoomOut")}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" onClick={() => applyZoom(1.3)} aria-label={t("zoomIn")}>
                <Plus size={14} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("zoomIn")}</TooltipContent>
          </Tooltip>
          <Popover open={helpOpen} onOpenChange={setHelpOpen}>
            <PopoverTrigger asChild>
              <Button
                variant={helpOpen ? "secondary" : "ghost"}
                size="icon-sm"
                aria-label={t("shortcutsHelp")}
              >
                <CircleHelp size={14} />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="tl-help" aria-label={t("shortcutsHelp")}>
              <strong>{t("shortcutsHelp")}</strong>
              {[
                ["Space", t("hintPlayPause")],
                ["A / B", t("hintTools")],
                ["S", t("hintSplit")],
                ["⌘D", t("hintDuplicate")],
                ["Delete", t("hintDelete")],
                ["⇧Delete", t("hintRipple")],
                ["⌘Z / ⇧⌘Z", t("hintUndoRedo")],
                ["← / →", t("hintFrameStep")],
                ["⇧点击", t("hintMultiSelect")],
                [t("hintDragLabel"), t("hintDragBody")],
                ["↕", t("hintVerticalDrag")],
              ].map(([key, body]) => (
                <div className="tl-help-row" key={key}>
                  <kbd>{key}</kbd>
                  <span>{body}</span>
                </div>
              ))}
            </PopoverContent>
          </Popover>
        </div>
      </div>
      <div className="tl-body">
        <div className="tl-labels" ref={labelsRef}>
          <div className="tl-labels-spacer" style={{ height: RULER_HEIGHT }} />
          {tracks.map((track) => (
            <div className="tl-label" key={track.id} style={{ height: TRACK_HEIGHT }}>
              <span className={`tl-label-dot dot-${track.kind}`} />
              {track.name}
              {onSetTrackState && (
                <span className="tl-label-tools">
                  <button
                    type="button"
                    className={track.muted ? "tl-label-tool on" : "tl-label-tool"}
                    aria-label={track.muted ? t("trackUnmute") : t("trackMute")}
                    onClick={() => onSetTrackState(track.id, { muted: !track.muted })}
                  >
                    {track.muted ? <VolumeX size={11} /> : <Volume2 size={11} />}
                  </button>
                  <button
                    type="button"
                    className={track.solo ? "tl-label-tool on" : "tl-label-tool"}
                    aria-label={track.solo ? t("trackUnsolo") : t("trackSolo")}
                    onClick={() => onSetTrackState(track.id, { solo: !track.solo })}
                  >
                    <span className="tl-label-badge">S</span>
                  </button>
                  {track.kind === "audio" && (
                    <button
                      type="button"
                      className={track.duck ? "tl-label-tool on" : "tl-label-tool"}
                      aria-label={track.duck ? t("trackUnduck") : t("trackDuck")}
                      onClick={() => onSetTrackState(track.id, { duck: !track.duck })}
                    >
                      <span className="tl-label-badge">D</span>
                    </button>
                  )}
                  <button
                    type="button"
                    className={track.locked ? "tl-label-tool on" : "tl-label-tool"}
                    aria-label={track.locked ? t("trackUnlock") : t("trackLock")}
                    onClick={() => onSetTrackState(track.id, { locked: !track.locked })}
                  >
                    {track.locked ? <Lock size={11} /> : <LockOpen size={11} />}
                  </button>
                </span>
              )}
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
        <div
          className="tl-hscroll"
          ref={hscrollRef}
          onScroll={(event) => {
            // Mirror vertical scroll to the labels column so track rows stay aligned.
            if (labelsRef.current) labelsRef.current.scrollTop = event.currentTarget.scrollTop;
          }}
        >
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
            {newLayerDrag && (
              <div className="tl-newlayer-hint" style={{ top: RULER_HEIGHT }}>
                <Plus size={12} /> {t("dropNewLayer")}
              </div>
            )}
            {tracks.map((track) => (
              <div
                className={
                  draggingAsset &&
                  ((track.kind === "video" && draggingAsset.kind !== "audio") ||
                    (track.kind === "audio" && draggingAsset.kind === "audio")) &&
                  !track.locked
                    ? "tl-lane droppable"
                    : "tl-lane"
                }
                key={track.id}
                style={{ height: TRACK_HEIGHT }}
                onDragOver={(event) => handleDragOver(event, track)}
                onDragLeave={() => dropGhost?.trackId === track.id && setDropGhost(null)}
                onDrop={(event) => handleDrop(event, track)}
                onPointerDown={(event) => {
                  if (event.target === event.currentTarget && event.button === 0) startMarquee(event);
                }}
              >
                {dropGhost?.trackId === track.id && (
                  <div
                    className="tl-drop-ghost"
                    style={{
                      left: timeToPx(dropGhost.start, pxPerSecond),
                      width: Math.max(12, timeToPx(dropGhost.duration, pxPerSecond)),
                    }}
                  />
                )}
                {dragDraft &&
                  dragDraft.kind === "move" &&
                  dragDraft.trackId === track.id &&
                  !(track.clips ?? []).some((item) => item.id === dragDraft.clipId) &&
                  (() => {
                    const source = allClips.find((item) => item.id === dragDraft.clipId);
                    if (!source) return null;
                    return (
                      <TimelineClip
                        key={`draft-${source.id}`}
                        trackKind={track.kind}
                        name={source.text_override ?? (source.asset_id ? assetById.get(source.asset_id)?.name ?? "" : "")}
                        left={timeToPx(dragDraft.timeline_start, pxPerSecond)}
                        width={Math.max(10, timeToPx((dragDraft.src_out - dragDraft.src_in) / (source.speed || 1), pxPerSecond))}
                        selected
                        dragging
                        onPointerDown={() => undefined}
                        onTrimPointerDown={() => undefined}
                        onSelect={() => undefined}
                      />
                    );
                  })()}
                {(track.clips ?? []).map((clip) => {
                  if (dragDraft && dragDraft.clipId === clip.id && dragDraft.trackId !== track.id) return null;
                  const draft = dragDraft && dragDraft.clipId === clip.id ? dragDraft : null;
                  const display = draft ?? clip;
                  // Insert-mode preview: clips at/after the drop point slide right by the
                  // dragged clip's duration, showing where the ripple will land them.
                  const partingShift =
                    insertRipple &&
                    insertRipple.trackId === track.id &&
                    clip.id !== dragDraft?.clipId &&
                    clip.timeline_start >= insertRipple.from - 1e-9
                      ? insertRipple.shift
                      : 0;
                  const displayLeft = display.timeline_start + partingShift;
                  const waveform = track.kind === "audio" && clip.asset_id ? waveformByAsset.get(clip.asset_id) : undefined;
                  const clipWidth = Math.max(10, timeToPx((display.src_out - display.src_in) / (clip.speed || 1), pxPerSecond));
                  const peaks =
                    waveform && clip.asset_id
                      ? cachedPeaks(peaksCache.current, clip.asset_id, waveform, display.src_in, display.src_out, clipWidth)
                      : undefined;
                  return (
                    <TimelineClip
                      key={clip.id}
                      trackKind={track.kind}
                      name={clip.text_override ?? (clip.asset_id ? assetById.get(clip.asset_id)?.name ?? clip.asset_id.slice(0, 8) : "")}
                      left={timeToPx(displayLeft, pxPerSecond)}
                      width={clipWidth}
                      selected={selectedClipIds.includes(clip.id)}
                      dragging={Boolean(draft)}
                      peaks={peaks}
                      onPointerDown={(event) => startClipDrag(event, track, clip.id)}
                      onTrimPointerDown={(event, edge) => startClipTrim(event, track, clip.id, edge)}
                      onSelect={() => {
                        if (!useEditorStore.getState().selectedClipIds.includes(clip.id)) selectClip(clip.id);
                      }}
                      onDelete={onDeleteClip ? () => onDeleteClip(clip.id) : undefined}
                      onRippleDelete={onRippleDeleteClip ? () => onRippleDeleteClip(clip.id) : undefined}
                      onSplit={onSplitClip ? () => onSplitClip(clip.id) : undefined}
                      onDuplicate={onDuplicateClip ? () => onDuplicateClip(clip.id) : undefined}
                    />
                  );
                })}
              </div>
            ))}
            {dragDraft &&
              (dragDraft.kind === "trim-start" || dragDraft.kind === "trim-end") &&
              (() => {
                const source = allClips.find((item) => item.id === dragDraft.clipId);
                if (!source) return null;
                const speed = source.speed || 1;
                const duration = (dragDraft.src_out - dragDraft.src_in) / speed;
                const edgeTime =
                  dragDraft.kind === "trim-start" ? dragDraft.timeline_start : dragDraft.timeline_start + duration;
                const trackIndex = tracks.findIndex((item) => item.id === dragDraft.trackId);
                if (trackIndex < 0) return null;
                return (
                  <div
                    className="tl-trim-hint"
                    style={{
                      left: timeToPx(edgeTime, pxPerSecond),
                      top: RULER_HEIGHT + trackIndex * TRACK_HEIGHT - 10,
                    }}
                  >
                    {formatTimecode(edgeTime)} · {duration.toFixed(2)}s
                  </div>
                );
              })()}
            {marquee && (
              <div
                className="tl-marquee"
                style={{
                  left: Math.min(marquee.x1, marquee.x2),
                  top: Math.min(marquee.y1, marquee.y2),
                  width: Math.abs(marquee.x2 - marquee.x1),
                  height: Math.abs(marquee.y2 - marquee.y1),
                }}
              />
            )}
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
